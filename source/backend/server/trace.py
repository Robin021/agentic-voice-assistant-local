from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import set_tracer_provider, get_tracer

from config import configure


set_tracer_provider(
    TracerProvider(resource=Resource(attributes={"service.name": configure.title}))
)
tracer = get_tracer(__name__)
