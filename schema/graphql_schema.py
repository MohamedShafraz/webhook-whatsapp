import strawberry

@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "Hello! Your GraphQL server is running with Strawberry on FastAPI!"

schema = strawberry.Schema(query=Query)
