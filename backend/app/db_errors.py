from pymongo.errors import ConfigurationError


def mongodb_unavailable_detail(exc: Exception) -> str:
    if isinstance(exc, ConfigurationError):
        return (
            "MongoDB Atlas hostname could not be resolved or its URI is invalid. "
            "Verify MONGODB_URI in backend/.env and check this computer's DNS/network. "
            "The server log shows the configured DNS resolver timed out; try a working DNS resolver."
        )
    return (
        "Cannot connect to MongoDB Atlas. Check that the cluster is active, this computer's current "
        "public IP is allowed in Atlas Network Access, and outbound port 27017 is available."
    )
