from parsers.santander import SantanderParserV1
from parsers.bbva import BBVAParserV1

PARSER_REGISTRY = {
    "santander": SantanderParserV1(),
    "bbva": BBVAParserV1(),
}