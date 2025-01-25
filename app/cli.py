import sys
from pathlib import Path

# Add the project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.utils.flow_utils import encrypt_flow_token, decrypt_flow_token
from app.scheduler import reset_daily_limits
from app.redis.engine import init_redis, disconnect_redis
import typer
import logging
import asyncio

logger = logging.getLogger(__name__)
cli = typer.Typer()


@cli.command()
def encrypt_flow_token_cli(
    wa_id: str = typer.Option(..., "--wa-id", help="WhatsApp ID"),
    flow_id: str = typer.Option(..., "--flow-id", help="Flow ID"),
):
    """Encrypt a flow token for testing flows.
    EXAMPLE: python app/cli.py encrypt_flow_token_cli --wa-id 1234 --flow-id 5678
    OR : uv run app/cli.py encrypt-flow-token-cli --wa-id 123456 --flow-id flow1234
    """
    try:
        logger.info(f"Encrypting flow token for wa_id {wa_id} and flow_id {flow_id}")
        result = encrypt_flow_token(wa_id, flow_id)
        result = "Encrypted flow token: " + result
        typer.echo(result)
    except Exception as e:
        logger.error(f"Error encrypting flow token: {e}")
        typer.echo("Error occurred. Check logs.", err=True)


@cli.command()
def decrypt_flow_token_cli(encrypted_flow_token: str):
    """Decrypt a flow token to extract wa_id and flow_id.
    EXAMPLE: python app/cli.py decrypt_flow_token_cli "encrypted_flow_token"
    OR : uv run app/cli.py decrypt-flow-token-cli "encrypted_flow_token"
    """
    try:
        logger.info(f"Decrypting flow token: {encrypted_flow_token}")
        result = decrypt_flow_token(encrypted_flow_token)
        result = "Decrypted flow token: " + str(result)
        typer.echo(result)
    except Exception as e:
        logger.error(f"Error decrypting flow token: {e}")
        typer.echo("Error occurred. Check logs.", err=True)


@cli.command()
def reset_daily_limits_cli():
    """Run the reset_daily_limits task.
    EXAMPLE: python app/cli.py reset_daily_limits_cli
    OR : uv run app/cli.py reset-daily-limits-cli
    """

    async def run_reset():
        await init_redis()
        await reset_daily_limits()
        await disconnect_redis()

    try:
        logger.info("Running reset_daily_limits task")
        asyncio.run(run_reset())
        typer.echo("Daily limits reset successfully")
    except Exception as e:
        logger.error(f"Error resetting daily limits: {e}")
        typer.echo("Error occurred. Check logs.", err=True)


if __name__ == "__main__":
    cli()


# TODO Add db reset script as a command here
