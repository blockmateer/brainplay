#!/usr/bin/env python3
"""
Generate embeddings for the Codenames wordlist.
Run this script once to precompute embeddings for all 400 words.
"""

import asyncio
import json
import os
from pathlib import Path
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def generate_word_embeddings():
    """
    Generate embeddings for all words in the wordlist and save to file.
    """
    # Paths
    script_dir = Path(__file__).parent
    wordlist_path = script_dir / "game" / "utils" / "wordlist-eng.txt"
    embeddings_path = script_dir / "game" / "utils" / "word_embeddings.json"
    
    # Check if wordlist exists
    if not wordlist_path.exists():
        print(f"Error: Wordlist not found at {wordlist_path}")
        return False
    
    # Read words
    with open(wordlist_path, 'r') as f:
        words = [line.strip() for line in f.readlines() if line.strip()]
    
    print(f"Found {len(words)} words in wordlist")
    
    # Initialize OpenAI client
    api_key = os.environ.get("OPENAI_KEY")
    if not api_key:
        print("Error: OPENAI_KEY environment variable not set")
        return False
    
    client = openai.AsyncOpenAI(api_key=api_key)
    
    # Generate embeddings in batches
    embeddings = {}
    batch_size = 100  # OpenAI allows up to 2048 inputs per request
    total_batches = (len(words) + batch_size - 1) // batch_size
    
    print(f"Processing {len(words)} words in {total_batches} batches of {batch_size}")
    
    try:
        for i in range(0, len(words), batch_size):
            batch_num = i // batch_size + 1
            batch = words[i:i+batch_size]
            
            print(f"Batch {batch_num}/{total_batches}: Processing words {i+1}-{min(i+batch_size, len(words))}")
            
            # Get embeddings for this batch
            response = await client.embeddings.create(
                model="text-embedding-3-large",
                input=batch
            )
            
            # Store embeddings
            for word, embedding_data in zip(batch, response.data):
                embeddings[word] = embedding_data.embedding
                print(f"  ✓ {word}: {len(embedding_data.embedding)} dimensions")
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)
        
        # Save embeddings to JSON file
        print(f"\nSaving embeddings to {embeddings_path}")
        with open(embeddings_path, 'w') as f:
            json.dump(embeddings, f, indent=2)
        
        print(f"✅ Successfully generated embeddings for {len(embeddings)} words")
        print(f"📁 Embeddings saved to: {embeddings_path}")
        
        # Verify the file
        file_size = embeddings_path.stat().st_size
        print(f"📊 File size: {file_size:,} bytes")
        
        return True
        
    except Exception as e:
        print(f"❌ Error generating embeddings: {e}")
        return False

async def verify_embeddings():
    """
    Verify that the generated embeddings file is valid.
    """
    script_dir = Path(__file__).parent
    embeddings_path = script_dir / "game" / "utils" / "word_embeddings.json"
    
    if not embeddings_path.exists():
        print("❌ Embeddings file not found")
        return False
    
    try:
        with open(embeddings_path, 'r') as f:
            embeddings = json.load(f)
        
        print(f"✅ Embeddings file loaded successfully")
        print(f"📊 Contains {len(embeddings)} words")
        
        # Check a few examples
        sample_words = list(embeddings.keys())[:3]
        for word in sample_words:
            embedding = embeddings[word]
            print(f"  {word}: {len(embedding)} dimensions, first 5 values: {embedding[:5]}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error verifying embeddings: {e}")
        return False

async def main():
    """
    Main function to generate and verify embeddings.
    """
    print("🚀 Starting word embedding generation...")
    print("=" * 50)
    
    # Generate embeddings
    success = await generate_word_embeddings()
    
    if success:
        print("\n" + "=" * 50)
        print("🔍 Verifying embeddings...")
        await verify_embeddings()
        
        print("\n" + "=" * 50)
        print("✅ Embedding generation complete!")
        print("\nNext steps:")
        print("1. The embeddings are saved in game/utils/word_embeddings.json")
        print("2. You can now use these embeddings in your miner")
        print("3. The embeddings will be loaded automatically when the miner starts")
    else:
        print("\n❌ Embedding generation failed!")

if __name__ == "__main__":
    asyncio.run(main())