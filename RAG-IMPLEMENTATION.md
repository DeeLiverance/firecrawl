# RAG Implementation Guide for Firecrawl

This guide explains how to use Firecrawl to create a RAG (Retrieval-Augmented Generation) system by crawling websites and processing the content for LLM consumption.

## Overview

Firecrawl provides powerful web crawling and content extraction capabilities that can be used to build a RAG system. This guide covers:

1. Crawling websites
2. Processing content for RAG
3. Vectorizing and storing data
4. Querying the knowledge base

## Prerequisites

- Node.js 16+
- Firecrawl API key (for cloud) or local setup
- Vector database (e.g., Pinecone, Weaviate, or FAISS)

## 1. Crawling Websites

Use Firecrawl's crawl API to extract content from websites:

```javascript
const { FirecrawlApp } = require('@mendable/firecrawl-js');

const firecrawl = new FirecrawlApp({ 
  apiKey: 'your-api-key' // Optional for local setup
});

async function crawlSite(url) {
  const { id: crawlId } = await firecrawl.crawlUrl(url, {
    crawlerOptions: {
      includeSubdomains: true,
      maxCrawled: 1000,
      respectRobotsTxt: true,
      maxDepth: 5
    },
    extractOptions: {
      includeMarkdown: true,
      includeHtml: false
    }
  });
  
  return crawlId;
}
```

## 2. Processing for RAG

Process crawled content into LLM-friendly chunks:

```javascript
const { RecursiveCharacterTextSplitter } = require('langchain/text_splitter');

async function processForRAG(crawlId) {
  // Get crawl results
  const results = await firecrawl.checkCrawlStatus(crawlId);
  
  // Initialize text splitter
  const textSplitter = new RecursiveCharacterTextSplitter({
    chunkSize: 1000,
    chunkOverlap: 200,
  });
  
  // Process each page
  const chunks = [];
  for (const page of results.data) {
    const pageChunks = await textSplitter.createDocuments(
      [page.markdown || page.content],
      [{
        url: page.url,
        title: page.metadata?.title || '',
        source: 'firecrawl',
        timestamp: new Date().toISOString()
      }]
    );
    chunks.push(...pageChunks);
  }
  
  return chunks;
}
```

## 3. Vector Storage

Store processed chunks in a vector database:

```javascript
const { Pinecone } = require('@pinecone-database/pinecone');
const { OpenAIEmbeddings } = require('@langchain/openai');

async function storeInVectorDB(chunks) {
  const embeddings = new OpenAIEmbeddings({
    openAIApiKey: 'your-openai-key'
  });
  
  const pinecone = new Pinecone();
  const index = pinecone.Index('rag-index');
  
  // Batch process chunks
  for (let i = 0; i < chunks.length; i += 100) {
    const batch = chunks.slice(i, i + 100);
    const vectors = await Promise.all(batch.map(async (chunk, idx) => ({
      id: `chunk-${i + idx}`,
      values: await embeddings.embedQuery(chunk.pageContent),
      metadata: {
        ...chunk.metadata,
        text: chunk.pageContent
      }
    })));
    
    await index.upsert(vectors);
  }
}
```

## 4. Querying the Knowledge Base

Query the vector database and generate responses:

```javascript
async function queryKnowledgeBase(query) {
  const queryEmbedding = await embeddings.embedQuery(query);
  
  const results = await index.query({
    vector: queryEmbedding,
    topK: 5,
    includeMetadata: true
  });
  
  // Format context for LLM
  const context = results.matches.map(match => ({
    content: match.metadata.text,
    source: match.metadata.url,
    score: match.score
  }));
  
  return context;
}
```

## Complete Example

Putting it all together:

```javascript
async function buildRAG(siteUrl) {
  // 1. Crawl the website
  const crawlId = await crawlSite(siteUrl);
  
  // 2. Process for RAG
  const chunks = await processForRAG(crawlId);
  
  // 3. Store in vector DB
  await storeInVectorDB(chunks);
  
  console.log('RAG system ready!');
}

// Build RAG system
buildRAG('https://example.com');
```

## Advanced Topics

### Incremental Updates

Use Firecrawl's change detection to update your knowledge base:

```javascript
const { data: changes } = await firecrawl.checkForChanges(crawlId);
```

### Custom Extractors

Define custom data extraction rules:

```javascript
const extractors = [{
  selector: '.product',
  schema: {
    name: 'h2',
    price: '.price',
    description: '.description'
  }
}];
```

### Rate Limiting

Control request rates to be respectful to target sites:

```javascript
crawlerOptions: {
  maxRequestsPerSecond: 2,
  maxConcurrency: 5
}
```

## Troubleshooting

- **Content not being captured**: Check if the content is loaded dynamically with JavaScript
- **Rate limiting**: Implement delays between requests
- **Authentication**: Use the `auth` option for protected content

## Next Steps

- Implement user authentication
- Add caching layer
- Set up monitoring and alerts
- Implement feedback loop for improving retrieval quality
