# Vercel Python entrypoint that exposes the Flask app as `app`
# The Vercel Python runtime looks for a global variable named `app` or `handler`.
from webapp import app

# For local running with `vercel dev` you can do:
if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple("0.0.0.0", 3000, app)
