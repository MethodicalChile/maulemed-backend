import os

# Solo para desarrollo local con http://localhost.
# No debe utilizarse en producción.
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow


load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

REDIRECT_URI = "http://localhost:8080/"


def main():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "Faltan GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET en el .env."
        )

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                REDIRECT_URI,
            ],
        }
    }

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    print("\nAbre esta URL en el navegador:\n")
    print(authorization_url)

    print(
        "\nDespués de aceptar, Google intentará redirigirte "
        "a http://localhost:8080/."
    )
    print(
        "Aunque la página no cargue, copia la URL completa "
        "desde la barra del navegador."
    )

    redirected_url = input(
        "\nPega aquí la URL completa: "
    ).strip()

    if not redirected_url.startswith(REDIRECT_URI):
        raise RuntimeError(
            "La URL ingresada no corresponde al callback configurado: "
            f"{REDIRECT_URI}"
        )

    try:
        flow.fetch_token(
            authorization_response=redirected_url,
        )
    except Exception as exc:
        raise RuntimeError(
            f"No fue posible intercambiar el código OAuth: {exc}"
        ) from exc

    credentials = flow.credentials

    if not credentials.refresh_token:
        raise RuntimeError(
            "Google no devolvió un refresh token. "
            "Verifica que usaste access_type='offline', "
            "prompt='consent' y que la cuenta esté autorizada "
            "como usuario de prueba."
        )

    print("\nRefresh token generado correctamente.")
    print("\nCopia esta línea en tu archivo .env:\n")
    print(
        f"GOOGLE_REFRESH_TOKEN={credentials.refresh_token}"
    )


if __name__ == "__main__":
    main()