# Vercel Python entrypoint that exposes the Flask app
from webapp import app as application

# For local running with `vercel dev` you can do:
if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple("0.0.0.0", 3000, application)
