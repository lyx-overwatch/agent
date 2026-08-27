"""Chat schemas.

The sync endpoint (POST /chat) has been removed.  Chat requests now use
form fields directly in the route handler; responses are SSE streamed.
"""

# This module is intentionally kept (even though it's currently empty)
# as a placeholder for future chat-related Pydantic models.
