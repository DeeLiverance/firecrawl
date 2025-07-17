# Firecrawl Self-Hosted Deployment & RAG Implementation Guide

> **Important Notice**: This guide is a supplementary resource. Always refer to the official documentation as the source of truth:
>
> - [Official SELF_HOST.md](SELF_HOST.md) - For self-hosting instructions
> - [Official README.md](README.md) - For general information and features

---

## ✅ Prerequisites

- [ ] Docker and Docker Compose installed
- [ ] OpenAI API key (for AI features)
- [ ] Minimum 4GB RAM, 2 CPU cores recommended
- [ ] Node.js 16+ (for development)

## 1. Initial Setup

### 1.1 Repository Setup

```bash
git clone https://github.com/mendableai/firecrawl.git
cd firecrawl
```

### 1.2 Environment Configuration

Create `.env` file with minimum required settings:

```bash
# ===== Required ENVS ======
PORT=3002
HOST=0.0.0.0

# Note: PORT is used by both the main API server and worker liveness check endpoint

# To turn on DB authentication, you need to set up Supabase
USE_DB_AUTHENTICATION=false

# This key lets you access the queue admin panel. Change this if your deployment is publicly accessible.
BULL_AUTH_KEY=CHANGEME

# ===== AI Features (Optional) =====
# OPENAI_API_KEY=your-api-key-here

# ===== System Resource Configuration =====
# Maximum CPU usage threshold (0.0-1.0)
MAX_CPU=0.8

# Maximum RAM usage threshold (0.0-1.0)
MAX_RAM=0.8

# ===== Playwright Settings =====
PLAYWRIGHT_TIMEOUT=30000  # ms

# ===== Redis Configuration =====
# These are autoconfigured by docker-compose.yaml
# REDIS_URL=redis://redis:6379
# REDIS_RATE_LIMIT_URL=redis://redis:6379
```

## 2. Docker Deployment

### 2.1 Start Services

```bash
docker compose build
docker compose up -d
```

> **Note**: Make sure you're using `docker compose` (with space) and not `docker-compose`. The commands are different and not interchangeable.

### 2.2 Verify Installation

1. Check health endpoint:

   ```bash
   curl -X GET http://localhost:3002/health
   ```

2. Access the Bull Queue Manager UI at:

   ```
   http://localhost:3002/admin/CHANGEME/queues
   ```

   > **Security Note**: Change the `CHANGEME` in the URL by setting a custom `BULL_AUTH_KEY` in your `.env` file.

## 3. Configuration

### 3.1 Core Settings

- [ ] Adjust worker count in `docker-compose.yml`
- [ ] Configure Redis persistence if needed
- [ ] Set up reverse proxy (Nginx/Caddy) for production

### 3.2 Rate Limiting

- [ ] Configure `MAX_CPU` and `MAX_RAM` based on host resources
- [ ] Set appropriate timeouts for different operations

## 4. RAG Pipeline Setup

### 4.1 Content Extraction

```javascript
// Example crawl configuration
const options = {
  excludeSelectors: ['nav', 'footer', '.ads'],
  respectRobotsTxt: true,
  maxCrawled: 1000,  // Adjust based on needs
  maxDepth: 3
};
```

### 4.2 Text Processing

- [ ] Install required packages:

  ```bash
  npm install langchain
  ```

- [ ] Configure text splitter:

  ```javascript
  const { RecursiveCharacterTextSplitter } = require('langchain/text_splitter');
  
  const splitter = new RecursiveCharacterTextSplitter({
    chunkSize: 1000,
    chunkOverlap: 200
  });
  ```

## 5. Quality Assurance

### 5.1 Testing

- [ ] Single URL test:

  ```bash
  curl -X POST http://localhost:3002/v1/scrape \
    -H 'Content-Type: application/json' \
    -d '{"url": "https://example.com"}'
  ```

- [ ] Full crawl test
- [ ] Verify markdown output quality

### 5.2 Monitoring

- [ ] Set up logging
- [ ] Monitor queue status at: `http://localhost:3002/admin/CHANGEME/queues`
- [ ] Track OpenAI token usage

## 6. Production Deployment

### 6.1 Scaling

```bash
docker compose up -d --scale worker=4
```

### 6.2 Maintenance

- [ ] Set up log rotation
- [ ] Configure backups
- [ ] Monitor resource usage

## 🚨 Troubleshooting

| Symptom | Possible Cause | Solution |
|---------|----------------|----------|
| High CPU usage | Too many workers | Reduce worker count |
| Timeout errors | Slow target sites | Increase `PLAYWRIGHT_TIMEOUT` |
| Missing content | Blocked by anti-bot | Adjust user-agent, add delays |
| API connection refused | Service not running | Check Docker logs: `docker logs [container_name]` |
| Supabase client errors | Supabase not configured | Set `USE_DB_AUTHENTICATION=false` if not using Supabase |
| Authentication bypass | Missing auth config | Warning: `You're bypassing authentication` means auth is disabled |
| Redis connection issues | Redis service down | Verify Redis is running and URLs are correct |

## 📈 Performance Optimization

```yaml
# Recommended thresholds
max_requests_per_domain: 5/sec
request_delay: 200  # ms between requests
max_retries: 3
chunk_size: 1000    # tokens
```

## 🔒 Security Considerations

- [ ] Change default `BULL_AUTH_KEY` to a secure value
- [ ] Set up firewall rules to restrict access to the admin panel
- [ ] Enable HTTPS for production deployments
- [ ] Rotate API keys regularly
- [ ] Monitor for abuse and failed login attempts
- [ ] Consider setting up a reverse proxy (Nginx/Caddy) with rate limiting
- [ ] Regularly update Docker images to get security patches

## 🔄 Maintenance Schedule

### Daily

- [ ] Check queue status
- [ ] Monitor error rates
- [ ] Verify backups

### Weekly

- [ ] Update dependencies
- [ ] Review logs
- [ ] Test restore procedure

## Next Steps

1. Run test crawl with sample URLs
2. Validate output quality
3. Gradually increase crawl limits
4. Set up monitoring alerts

## Resources

- [Firecrawl Documentation](https://docs.firecrawl.dev)
- [Docker Documentation](https://docs.docker.com)
- [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
