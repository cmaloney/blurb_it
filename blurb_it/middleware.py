import aiohttp
import aiohttp_jinja2
from aiohttp import web

CERTIFICATE_ERROR_MESSAGE = (
    "SSL certificate verification failed when connecting to GitHub. "
    "On macOS with Python from python.org, run: "
    'open "/Applications/Python 3.x/Install Certificates.command" '
    "(replace 3.x with your Python version)."
)


@web.middleware
async def error_middleware(request, handler):
    """Middleware to render error message using the template renderer."""
    try:
        response = await handler(request)
    except web.HTTPException as ex:
        if ex.text:
            message = ex.text
        else:
            message = ex.reason
        context = {"error_message": message, "status": ex.status}
        response = aiohttp_jinja2.render_template(
            "error.html", request, context=context
        )
    except aiohttp.ClientConnectorCertificateError:
        context = {"error_message": CERTIFICATE_ERROR_MESSAGE, "status": 500}
        response = aiohttp_jinja2.render_template(
            "error.html", request, context=context
        )
    return response
