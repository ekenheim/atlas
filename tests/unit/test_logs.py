import logging

import pytest

from atlas.logs import configure_logging


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("connecting to postgresql+psycopg://atlas:s3cr3t-pw@db:5432/atlas", "s3cr3t-pw"),
        ("calling hindsight with Authorization: Bearer hs-token-123", "hs-token-123"),
        ("litellm key sk-abcdefghijklmnop1234 rejected", "sk-abcdefghijklmnop1234"),
        ("s3 aws_secret_access_key=wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI/K7MDENG"),
    ],
)
def test_secrets_never_reach_the_log_output(
    message: str, secret: str, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging()

    logging.getLogger("atlas.test").warning(message)

    err = capsys.readouterr().err
    assert secret not in err
    assert "[REDACTED]" in err


def test_ordinary_messages_pass_through_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()

    logging.getLogger("atlas.test").info("database migrated to head")

    assert '"message": "database migrated to head"' in capsys.readouterr().err
