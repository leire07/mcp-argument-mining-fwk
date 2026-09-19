import os
from pathlib import Path

from openai import APITimeoutError, OpenAI


def cargar_env():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        raise RuntimeError(f"No se encuentra el archivo {env_path}")

    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("'\""))


def crear_cliente():
    cargar_env()
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")

    if not base_url or not api_key:
        raise RuntimeError(
            "Define OPENAI_BASE_URL y OPENAI_API_KEY en el archivo .env."
        )

    return OpenAI(
        base_url=base_url.strip(),
        api_key=api_key.strip(),
        timeout=120.0,
        max_retries=3,
    )


def call_llm(client, model, prompt):
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    try:
        client = crear_cliente()
        respuesta = call_llm(
            client,
            "gpt-oss-120b",
            "\u00bfQu\u00e9 es la IA generativa?",
        )
        print(respuesta)
    except APITimeoutError:
        raise SystemExit(
            "No se pudo conectar con PoliGPT. Con\u00e9ctate a la red de la UPV "
            "o activa la VPN de la UPV y vuelve a ejecutar el programa."
        )
