import google.generativeai as genai
import os

# PASTE YOUR API KEY HERE
API_KEY = "AIzaSyC0BfWRztjVBWVgy8wMW_KABpld2F0BADA"
genai.configure(api_key=API_KEY)

print("Searching for available models...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error: {e}")