from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


HANDLER_PATH = Path(__file__).resolve().parents[1] / "infra" / "lambda" / "handler.py"
SPEC = spec_from_file_location("capstone_lambda_handler", HANDLER_PATH)
MODULE = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Context:
    aws_request_id = "request-123"


def test_lambda_handler_extracts_s3_object_metadata():
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "example-lake"},
                    "object": {"key": "bronze/orders/page+1.json"},
                }
            }
        ]
    }
    result = MODULE.handler(event, Context())
    assert result == {
        "processed": 1,
        "objects": [{"bucket": "example-lake", "key": "bronze/orders/page 1.json"}],
    }

