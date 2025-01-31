import sys
from pathlib import Path

# Add the project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.utils.flow_utils import encrypt_flow_token, decrypt_flow_token
import typer
import logging
import subprocess

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
def flows_encryption_cli(
    phone_number_id: str = typer.Option(
        ..., "--phone-number-id", help="WhatsApp business phone number ID"
    ),
    access_token: str = typer.Option(
        ..., "--access-token", help="System user access token"
    ),
    file_name: str = typer.Option(
        "rsa_key", "--file-name", help="Base name for PEM files"
    ),
    passphrase: str = typer.Option(
        ..., "--passphrase", help="Passphrase for the RSA key"
    ),
):
    """
    Single command that generates keys, sets them, and then retrieves them to confirm.

    EXAMPLE:
    uv run python -m scripts.flows.cli flows-encryption-cli --phone-number-id 434184924443332 --access-token ADASD23sads4342ADSFASdf --file-name prod_rsa_key --passphrase ttsdf@2433423
    """
    try:
        # Generate keys
        subprocess.run(
            [
                "openssl",
                "genrsa",
                "-des3",
                "-passout",
                f"pass:{passphrase}",
                "-out",
                f"{file_name}.pem",
                "2048",
            ],
            check=True,
        )
        subprocess.run(
            [
                "openssl",
                "rsa",
                "-in",
                f"{file_name}.pem",
                "-passin",
                f"pass:{passphrase}",
                "-outform",
                "PEM",
                "-pubout",
                "-out",
                f"{file_name}_pub.pem",
            ],
            check=True,
        )
        typer.echo(f"Key pair generated: {file_name}.pem and {file_name}_pub.pem")

        # Read the public key from the file
        with open(f"{file_name}_pub.pem", "r") as pub_key_file:
            public_key = pub_key_file.read()

        # Set key
        set_key_response = subprocess.run(
            [
                "curl",
                "-X",
                "POST",
                f"https://graph.facebook.com/v22.0/{phone_number_id}/whatsapp_business_encryption",
                "-H",
                f"Authorization: Bearer {access_token}",
                "-H",
                "Content-Type: application/x-www-form-urlencoded",
                "--data-urlencode",
                f"business_public_key={public_key}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        typer.echo(set_key_response.stdout)

        # Get key
        get_key_response = subprocess.run(
            [
                "curl",
                "-X",
                "GET",
                f"https://graph.facebook.com/v22.0/{phone_number_id}/whatsapp_business_encryption",
                "-H",
                f"Authorization: Bearer {access_token}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        typer.echo(get_key_response.stdout)

    except subprocess.CalledProcessError as e:
        typer.echo(f"Error: {e.stderr}")


if __name__ == "__main__":
    cli()


# TODO Add db reset script as a command here
