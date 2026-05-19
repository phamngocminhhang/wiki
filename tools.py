import datetime
import json
import os
import logging
from pymongo import MongoClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Connect to MongoDB
client = MongoClient('mongodb+srv://dbUser:Rmit1234_@cluster0.uyfgear.mongodb.net/?appName=Cluster0')
db = client['wiki']
logger.info("Connected to MongoDB")

def upsert_book(book_url, book_data):
    # Migrate books_queue.json
    base_dir = os.path.dirname(os.path.abspath(__file__))
    book_queue = os.path.join(base_dir, 'books_queue.json')
    cache_dir = os.path.join(base_dir, 'book_cache')

    with open(book_queue, 'r', encoding='utf-8') as f:
        queue_data = json.load(f)
    logger.info(f"Loaded {len(queue_data['books'])} books from queue")


    for book in queue_data['books']:
        if book.get('status') == 'done':
            path = os.path.join(cache_dir, book['book_url'].split('/')[-1] + '.json')
            with open(path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            logger.info(f"Backup book: {book.get('book_url', 'Unknown')}")
            result = db.book_info.update_one({'book_url': book['book_url']}, {'$set': book}, upsert=True)
            if result.upserted_id:
                book_id = result.upserted_id
                logger.info(f"Inserted book_info with ID: {book_id}")
            else:
                book_id = db.book_info.find_one({'book_url': book['book_url']})['_id']
                logger.info(f"Updated book_info with ID: {book_id}")


            chapters = db.book_chapters.update_one({'book_id': book_id}, {'$set': cache_data}, upsert=True)
            if chapters.upserted_id:
                logger.info(f"Inserted book_chapters with ID: {chapters.upserted_id}")
            else:
                logger.info(f"Updated book_chapters for book_id: {book_id}")

    logger.info("Migration complete!")
    
    
def download_fromdb():
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, 'output.json')
    collection = db['book_info']

    # Extract all documents
    documents = list(collection.find())

    # Convert ObjectId to string for JSON serialization
    for doc in documents:
        doc["_id"] = str(doc["_id"])

    # Save to JSON file
    with open(path, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)

    print(f"Exported {len(documents)} documents to {path}")
    

def extract():

    import os
    import json
    from datetime import datetime

    # Folder containing book JSON files
    base_dir = os.path.dirname(os.path.abspath(__file__))
    BOOKS_FOLDER = os.path.join(base_dir, "book_cache")

    # Output file
    OUTPUT_FILE =  os.path.join(base_dir, "downloaded_books.json")

    downloaded_books = []

    # Loop through all JSON files
    for filename in os.listdir(BOOKS_FOLDER):

        # Only process .json files
        if not filename.endswith(".json"):
            continue

        file_path = os.path.join(BOOKS_FOLDER, filename)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            metadata = data.get("metadata", {})
            chapters = data.get("chapters", [])

            total_chapters = len(chapters)
            downloaded_chapters = sum(
                1 for chapter in chapters if chapter.get("downloaded") is True
            )

            # Check if all chapters are downloaded
            if total_chapters > 0 and downloaded_chapters == total_chapters:

                downloaded_books.append({
                    "book_url": metadata.get("book_url"),
                    "status": "done",
                    "added_at": datetime.utcnow().isoformat(),
                    "title": metadata.get("title"),
                    "author": metadata.get("author"),
                    "cover_url": metadata.get("cover_url"),
                    "total_chapters": total_chapters,
                    "downloaded_chapters": downloaded_chapters,
                    "epub_path": None,
                    "error": None,
                    "json_file": filename  # keep original json filename
                })

                print(f"✓ Downloaded: {filename}")

        except Exception as e:
            print(f"Error reading {filename}: {e}")

    # Save result
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(downloaded_books, f, ensure_ascii=False, indent=4)

    print(f"\nSaved {len(downloaded_books)} downloaded books to {OUTPUT_FILE}")
extract()