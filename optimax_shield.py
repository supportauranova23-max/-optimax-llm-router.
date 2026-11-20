import re, httpx

class OptiMaxShieldSDK:
    """Open-Source Client-Side PII & Secret Redactor for OptiMax Quantum."""
    PATTERNS = {
        "SECRET_KEY": r"(?:sk-|AIza|gsk_|optx_|ghp_)[a-zA-Z0-9_-]{16,}",
        "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "CARD": r"\b(?:\d[ -]*?){13,16}\b"
    }

    def __init__(self, api_key: str, base_url: str = "https://onrender.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def redact(self, text: str):
        vault = {}
        for label, pat in self.PATTERNS.items():
            for i, m in enumerate(re.findall(pat, text)):
                tok = f"[{label}_{i}]"
                vault[tok] = m
                text = text.replace(m, tok, 1)
        return text, vault

    def chat(self, prompt: str, preset: str = "max_savings") -> dict:
        clean_p, vault = self.redact(prompt)
        r = httpx.post(
            f"{self.base_url}/route",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"prompt": clean_p, "preset": preset},
            timeout=25.0
        )
        data = r.json()
        if "response" in data:
            for tok, orig in vault.items():
                data["response"] = data["response"].replace(tok, orig)
        data["client_side_redacted"] = len(vault)
        return data
