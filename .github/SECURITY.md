# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| v1.3.x  | :white_check_mark: |
| v1.2.x  | :white_check_mark: |
| v1.1.x  | :white_check_mark: |
| < v1.0  | :x:                |

## Reporting a Vulnerability

We take the security of QuantTrading seriously. If you believe you have found a security vulnerability, please follow these steps:

### Private Vulnerability Reporting

1. **Do NOT open a public GitHub Issue** for security vulnerabilities.
2. Use GitHub's **Private Vulnerability Reporting** feature:
   - Go to the repository's **Security** tab
   - Click **Report a vulnerability**
   - Provide a detailed description of the vulnerability
3. Alternatively, email: teliduxlng@qq.com with the subject `[SECURITY] QuantTrading`

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)
- Your contact information

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 72 hours
- **Fix Release**: Within 7 days for critical, 30 days for moderate

## Security Features

This project includes the following security measures:

- **API Key Protection**: All API keys are stored in environment variables (.env), never hardcoded
- **Authentication Middleware**: API Key authentication on all endpoints
- **Rate Limiting**: Built-in rate limiter to prevent abuse
- **Input Validation**: All inputs validated using Pydantic
- **CORS Configuration**: Configurable cross-origin resource sharing
- **Dependency Scanning**: Dependabot enabled for vulnerability detection
- **Code Scanning**: CodeQL static analysis (when enabled)
- **Secret Scanning**: GitHub secret scanning enabled
- **Push Protection**: Prevents committing known secrets

## Best Practices for Users

1. **Never commit API keys** - Use `.env` file (already in `.gitignore`)
2. **Use demo mode** - Set `OKX_DEMO=true` for testing
3. **Regularly rotate keys** - Update your API keys periodically
4. **Review permissions** - Only grant necessary scopes to tokens
5. **Enable 2FA** - Use two-factor authentication on your GitHub account

## Security Checklist for Contributors

- [ ] No hardcoded API keys or secrets
- [ ] `.env` file is in `.gitignore`
- [ ] Input validation on all new endpoints
- [ ] No SQL injection vulnerabilities
- [ ] No XSS vulnerabilities
- [ ] Dependencies are up to date
- [ ] `flake8` passes without errors
