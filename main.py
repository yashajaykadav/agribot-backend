# main.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from pypdf import PdfReader
import io
import os
import shutil
from pathlib import Path
from typing import List

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURATION ---
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise ValueError("No API Key found! Set GOOGLE_API_KEY in environment variables.")
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-flash-latest')


PDF_FOLDER = Path("./pdfs")  # Create this folder and put your PDFs here

pdf_contexts = {}  # {filename: text_content}
combined_context = ""

def load_all_pdfs():
    """Load all PDFs from the PDF_FOLDER on server startup"""
    global pdf_contexts, combined_context
    
    # Create folder if it doesn't exist
    PDF_FOLDER.mkdir(exist_ok=True)
    
    pdf_contexts = {}
    
    # Find all PDF files
    pdf_files = list(PDF_FOLDER.glob("*.pdf"))
    
    if not pdf_files:
        print("⚠️ No PDF files found in ./pdfs folder")
        return
    
    print(f"📚 Loading {len(pdf_files)} PDF files...")
    
    for pdf_path in pdf_files:
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            
            if text.strip():
                pdf_contexts[pdf_path.name] = text
                print(f"  ✅ Loaded: {pdf_path.name} ({len(text)} chars)")
            else:
                print(f"  ⚠️ Empty or unreadable: {pdf_path.name}")
                
        except Exception as e:
            print(f"  ❌ Error loading {pdf_path.name}: {e}")
    
    # Combine all contexts
    combined_context = "\n\n---\n\n".join([
        f"[From: {filename}]\n{content}" 
        for filename, content in pdf_contexts.items()
    ])
    
    print(f"📖 Total context loaded: {len(combined_context)} characters from {len(pdf_contexts)} files")

# Load PDFs when server starts
@app.on_event("startup")
async def startup_event():
    load_all_pdfs()

@app.get("/")
async def root():
    """Health check and info endpoint"""
    return {
        "status": "running",
        "loaded_pdfs": list(pdf_contexts.keys()),
        "total_pdfs": len(pdf_contexts),
        "total_context_length": len(combined_context)
    }

@app.get("/pdfs")
async def list_pdfs():
    """List all loaded PDFs"""
    return {
        "pdfs": [
            {
                "filename": name,
                "size": len(content),
                "preview": content[:200] + "..." if len(content) > 200 else content
            }
            for name, content in pdf_contexts.items()
        ]
    }

@app.post("/reload")
async def reload_pdfs():
    """Reload all PDFs from the folder"""
    load_all_pdfs()
    return {
        "status": "success",
        "loaded_pdfs": list(pdf_contexts.keys()),
        "total": len(pdf_contexts)
    }

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a new PDF and add to context"""
    global pdf_contexts, combined_context
    
    try:
        # Save to PDF folder
        file_path = PDF_FOLDER / file.filename
        
        content = await file.read()
        
        # Save file
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Extract text
        pdf_reader = PdfReader(io.BytesIO(content))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        # Add to context
        pdf_contexts[file.filename] = text
        
        # Rebuild combined context
        combined_context = "\n\n---\n\n".join([
            f"[From: {filename}]\n{content}" 
            for filename, content in pdf_contexts.items()
        ])
        
        print(f"✅ Uploaded: {file.filename} ({len(text)} chars)")
        
        return {
            "status": "success",
            "message": f"PDF '{file.filename}' loaded!",
            "total_pdfs": len(pdf_contexts)
        }
        
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return {"status": "error", "message": str(e)}

@app.delete("/pdf/{filename}")
async def delete_pdf(filename: str):
    """Delete a PDF from context and folder"""
    global pdf_contexts, combined_context
    
    try:
        # Remove from context
        if filename in pdf_contexts:
            del pdf_contexts[filename]
        
        # Remove file
        file_path = PDF_FOLDER / filename
        if file_path.exists():
            os.remove(file_path)
        
        # Rebuild combined context
        combined_context = "\n\n---\n\n".join([
            f"[From: {fname}]\n{content}" 
            for fname, content in pdf_contexts.items()
        ])
        
        return {"status": "success", "message": f"Deleted {filename}"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/chat")
async def chat_endpoint(
    question: str = Form(None), 
    audio: UploadFile = File(None),
    use_context: bool = Form(True)  # Option to disable PDF context
):
    """Chat with the AI using PDF context"""
    global combined_context
    
    # 1. Prepare the Prompt Context
    if use_context and combined_context:
        context_text = combined_context
        context_info = f"Using context from {len(pdf_contexts)} PDF documents."
    else:
        context_text = "No PDF documents loaded. Use general agriculture knowledge."
        context_info = "No PDF context available."
    
    # Limit context to avoid token limits (approximately 100k chars)
    if len(context_text) > 100000:
        context_text = context_text[:100000] + "\n...[Context truncated due to length]..."
    
    prompt = f"""
    You are an expert agriculture consultant (AgriBot) for Indian Farmers.
    
    INSTRUCTIONS:
    - Answer in the same language the user uses (Marathi/Hindi/English)
    - Keep the answer short, clear and helpful
    - Use bullet points and formatting when listing information
    - If information is from the PDF documents, mention which document
    - If you don't find relevant info in documents, use general knowledge but mention it
    
    AVAILABLE DOCUMENTS: {list(pdf_contexts.keys()) if pdf_contexts else "None"}
    
    DOCUMENT CONTENTS:
    {context_text}
    
    ---
    
    Now answer the user's question based on the above context:
    """
    
    try:
        content_parts = [prompt]

        # 2. Handle Audio (Voice Message)
        if audio:
            print("🎤 Processing Audio...")
            temp_path = "temp_audio.m4a"
            
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(audio.file, buffer)
            
            myfile = genai.upload_file(temp_path)
            content_parts.append(myfile)
            
            # Clean up
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 3. Handle Text
        if question:
            print(f"💬 Question: {question}")
            content_parts.append(question)

        # 4. Ask Gemini
        response = model.generate_content(content_parts)
        
        print(f"✅ Response generated ({len(response.text)} chars)")
        
        return {
            "answer": response.text,
            "context_used": list(pdf_contexts.keys()),
            "context_info": context_info
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        return {"answer": f"Sorry, I faced an error: {str(e)}"}


# ========== SPECIFIC DOCUMENT QUERY ==========
@app.post("/query/{filename}")
async def query_specific_pdf(filename: str, question: str = Form(...)):
    """Query a specific PDF document"""
    
    if filename not in pdf_contexts:
        return {"error": f"PDF '{filename}' not found"}
    
    context = pdf_contexts[filename]
    
    prompt = f"""
    You are an expert agriculture consultant analyzing a specific document.
    Answer in the language the user uses (Marathi/Hindi/English).
    
    DOCUMENT: {filename}
    
    CONTENT:
    {context[:50000]}  # Limit to 50k chars per document
    
    ---
    
    User Question: {question}
    """
    
    try:
        response = model.generate_content(prompt)
        return {
            "answer": response.text,
            "document": filename
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)