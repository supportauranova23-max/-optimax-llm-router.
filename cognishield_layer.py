class CogniShieldLayer:
    def __init__(self):
        # Initializing core rules for payload threat scanning
        self.forbidden_patterns = ["DROP TABLE", "OR 1=1", "<script>", "EXEC("]

    def inspect_payload(self, prompt: str) -> dict:
        """
        Inspects incoming client prompts for injection attempts or malicious payload structures.
        """
        if not prompt:
            return {"safe": True, "reason": "Empty payload allowed"}
            
        upper_prompt = prompt.upper()
        for pattern in self.forbidden_patterns:
            if pattern in upper_prompt:
                return {
                    "safe": False, 
                    "reason": f"Malicious syntax pattern detected matching: {pattern}"
                }
                
        return {"safe": True, "reason": "Security scan cleared successfully"}

