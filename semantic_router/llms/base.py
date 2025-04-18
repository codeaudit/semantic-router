import json
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from semantic_router.schema import Message
from semantic_router.utils.logger import logger


class BaseLLM(BaseModel):
    """Base class for LLMs typically used by dynamic routes.

    This class provides a base implementation for LLMs. It defines the common
    configuration and methods for all LLM classes.
    """

    name: str
    temperature: Optional[float] = 0.0
    max_tokens: Optional[int] = None

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, name: str, **kwargs):
        """Initialize the BaseLLM.

        :param name: The name of the LLM.
        :type name: str
        :param **kwargs: Additional keyword arguments for the LLM.
        :type **kwargs: dict
        """
        super().__init__(name=name, **kwargs)

    def __call__(self, messages: List[Message]) -> Optional[str]:
        """Call the LLM.

        Must be implemented by subclasses.

        :param messages: The messages to pass to the LLM.
        :type messages: List[Message]
        :return: The response from the LLM.
        :rtype: Optional[str]
        """
        raise NotImplementedError("Subclasses must implement this method")

    def _check_for_mandatory_inputs(
        self, inputs: dict[str, Any], mandatory_params: List[str]
    ) -> bool:
        """Check for mandatory parameters in inputs.

        :param inputs: The inputs to check for mandatory parameters.
        :type inputs: dict[str, Any]
        :param mandatory_params: The mandatory parameters to check for.
        :type mandatory_params: List[str]
        :return: True if all mandatory parameters are present, False otherwise.
        :rtype: bool
        """
        for name in mandatory_params:
            if name not in inputs:
                logger.error(f"Mandatory input {name} missing from query")
                return False
        return True

    def _check_for_extra_inputs(
        self, inputs: dict[str, Any], all_params: List[str]
    ) -> bool:
        """Check for extra parameters not defined in the signature.

        :param inputs: The inputs to check for extra parameters.
        :type inputs: dict[str, Any]
        :param all_params: The all parameters to check for.
        :type all_params: List[str]
        :return: True if all extra parameters are present, False otherwise.
        :rtype: bool
        """
        input_keys = set(inputs.keys())
        param_keys = set(all_params)
        if not input_keys.issubset(param_keys):
            extra_keys = input_keys - param_keys
            logger.error(
                f"Extra inputs provided that are not in the signature: {extra_keys}"
            )
            return False
        return True

    def _is_valid_inputs(
        self, inputs: List[Dict[str, Any]], function_schemas: List[Dict[str, Any]]
    ) -> bool:
        """Determine if the functions chosen by the LLM exist within the function_schemas,
        and if the input arguments are valid for those functions.

        :param inputs: The inputs to check for validity.
        :type inputs: List[Dict[str, Any]]
        :param function_schemas: The function schemas to check against.
        :type function_schemas: List[Dict[str, Any]]
        :return: True if the inputs are valid, False otherwise.
        :rtype: bool
        """
        try:
            # Currently only supporting single functions for most LLMs in Dynamic Routes.
            if len(inputs) != 1:
                logger.error("Only one set of function inputs is allowed.")
                return False
            if len(function_schemas) != 1:
                logger.error("Only one function schema is allowed.")
                return False
            # Validate the inputs against the function schema
            if not self._validate_single_function_inputs(
                inputs[0], function_schemas[0]
            ):
                return False

            return True
        except Exception as e:
            logger.error(f"Input validation error: {str(e)}")
            return False

    def _validate_single_function_inputs(
        self, inputs: Dict[str, Any], function_schema: Dict[str, Any]
    ) -> bool:
        """Validate the extracted inputs against the function schema.

        :param inputs: The inputs to validate.
        :type inputs: Dict[str, Any]
        :param function_schema: The function schema to validate against.
        :type function_schema: Dict[str, Any]
        :return: True if the inputs are valid, False otherwise.
        :rtype: bool
        """
        try:
            # Extract parameter names and determine if they are optional
            signature = function_schema["signature"]
            param_info = [param.strip() for param in signature[1:-1].split(",")]
            mandatory_params = []
            all_params = []

            for info in param_info:
                parts = info.split("=")
                name_type_pair = parts[0].strip()
                if ":" in name_type_pair:
                    name, _ = name_type_pair.split(":")
                else:
                    name = name_type_pair
                all_params.append(name)

                # If there is no default value, it's a mandatory parameter
                if len(parts) == 1:
                    mandatory_params.append(name)

            # Check for mandatory parameters
            if not self._check_for_mandatory_inputs(inputs, mandatory_params):
                return False

            # Check for extra parameters not defined in the signature
            if not self._check_for_extra_inputs(inputs, all_params):
                return False

            return True
        except Exception as e:
            logger.error(f"Single input validation error: {str(e)}")
            return False

    def _extract_parameter_info(self, signature: str) -> tuple[List[str], List[str]]:
        """Extract parameter names and types from the function signature.

        :param signature: The function signature to extract parameter names and types from.
        :type signature: str
        :return: A tuple of parameter names and types.
        :rtype: tuple[List[str], List[str]]
        """
        param_info = [param.strip() for param in signature[1:-1].split(",")]
        param_names = [info.split(":")[0].strip() for info in param_info]
        param_types = [
            info.split(":")[1].strip().split("=")[0].strip() for info in param_info
        ]
        return param_names, param_types

    def extract_function_inputs(
        self, query: str, function_schemas: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract the function inputs from the query.

        :param query: The query to extract the function inputs from.
        :type query: str
        :param function_schemas: The function schemas to extract the function inputs from.
        :type function_schemas: List[Dict[str, Any]]
        :return: The function inputs.
        :rtype: List[Dict[str, Any]]
        """
        logger.info("Extracting function input...")

        prompt = f"""
You are an accurate and reliable computer program that only outputs valid JSON. 
Your task is to output JSON representing the input arguments of a Python function.

This is the Python function's schema:

### FUNCTION_SCHEMAS Start ###
	{function_schemas}
### FUNCTION_SCHEMAS End ###

This is the input query.

### QUERY Start ###
	{query}
### QUERY End ###

The arguments that you need to provide values for, together with their datatypes, are stated in "signature" in the FUNCTION_SCHEMAS.
The values these arguments must take are made clear by the QUERY.
Use the FUNCTION_SCHEMAS "description" too, as this might provide helpful clues about the arguments and their values.
Return only JSON, stating the argument names and their corresponding values.

### FORMATTING_INSTRUCTIONS Start ###
	Return a respones in valid JSON format. Do not return any other explanation or text, just the JSON.
	The JSON-Keys are the names of the arguments, and JSON-values are the values those arguments should take.
### FORMATTING_INSTRUCTIONS End ###

### EXAMPLE Start ###
	=== EXAMPLE_INPUT_QUERY Start ===
		"How is the weather in Hawaii right now in International units?"
	=== EXAMPLE_INPUT_QUERY End ===
	=== EXAMPLE_INPUT_SCHEMA Start ===
		{{
			"name": "get_weather",
			"description": "Useful to get the weather in a specific location",
			"signature": "(location: str, degree: str) -> str",
			"output": "<class 'str'>",
		}}
	=== EXAMPLE_INPUT_QUERY End ===
	=== EXAMPLE_OUTPUT Start ===
		{{
			"location": "Hawaii",
			"degree": "Celsius",
		}}
	=== EXAMPLE_OUTPUT End ===
### EXAMPLE End ###

Note: I will tip $500 for an accurate JSON output. You will be penalized for an inaccurate JSON output.

Provide JSON output now:
"""
        llm_input = [Message(role="user", content=prompt)]
        output = self(llm_input)
        if not output:
            raise Exception("No output generated for extract function input")
        output = output.replace("'", '"').strip().rstrip(",")
        logger.info(f"LLM output: {output}")
        function_inputs = json.loads(output)
        if not isinstance(function_inputs, list):
            function_inputs = [function_inputs]
        logger.info(f"Function inputs: {function_inputs}")
        if not self._is_valid_inputs(function_inputs, function_schemas):
            raise ValueError("Invalid inputs")
        return function_inputs
