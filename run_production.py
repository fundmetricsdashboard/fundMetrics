from waitress import serve
from app import app

if __name__ == '__main__':
    print("Starting production server on http://127.0.0.1:5000")
    serve(app, host='127.0.0.1', port=5000, threads=4)