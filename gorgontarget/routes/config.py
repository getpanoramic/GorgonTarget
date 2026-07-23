from fastapi import APIRouter, Depends, Query
from ..utils import get_medusa_key, logger
from ..client import MedusaClient

router = APIRouter()

async def get_medusa_client(api_key: str = Depends(get_medusa_key)):
    return MedusaClient(api_key)

@router.get("/api/v3/config/ui")
async def get_config_ui():
    return {
        "id": 1,
        "firstDayOfWeek": 1,
        "calendarWeekColumnHeader": None,
        "shortDateFormat": None,
        "longDateFormat": None,
        "timeFormat": None,
        "showRelativeDates": True,
        "enableColorImpairedMode": True,
        "theme": None,
        "uiLanguage": 1
    }

@router.get("/api/v3/config/host")
async def get_config_host(client: MedusaClient = Depends(get_medusa_client)):
    config = await client.get_system_config()
    main = config.get("main", {})
    web_interface = main.get("webInterface", {})
    logs = main.get("logs", {})
    git = main.get("git", {})

    # Map Medusa config to the new schema
    return {
        "id": 1,
        "bindAddress": web_interface.get("host"),
        "port": web_interface.get("port"),
        "sslPort": web_interface.get("port") if web_interface.get("httpsEnable") else 0,
        "enableSsl": web_interface.get("httpsEnable", False),
        "launchBrowser": main.get("launchBrowser", False),
        "authenticationMethod": "basic" if web_interface.get("username") else "none",
        "authenticationRequired": "enabled" if web_interface.get("username") else "disabled",
        "analyticsEnabled": True,
        "username": web_interface.get("username"),
        "password": web_interface.get("password"),
        "passwordConfirmation": web_interface.get("password"),
        "logLevel": "info",
        "logSizeLimit": logs.get("size", 20),
        "consoleLogLevel": "info",
        "branch": git.get("branch") or "master",
        "apiKey": web_interface.get("apiKey"),
        "sslCertPath": web_interface.get("httpsCert"),
        "sslCertPassword": web_interface.get("httpsKey"),
        "urlBase": main.get("webRoot"),
        "instanceName": "GorgonTarget",
        "applicationUrl": None,
        "updateAutomatically": main.get("autoUpdate", False),
        "updateMechanism": "builtIn",
        "updateScriptPath": None,
        "proxyEnabled": bool(main.get("proxySetting")),
        "proxyType": "http",
        "proxyHostname": None,
        "proxyPort": 0,
        "proxyUsername": None,
        "proxyPassword": None,
        "proxyBypassFilter": None,
        "proxyBypassLocalAddresses": True,
        "certificateValidation": "enabled",
        "backupFolder": None,
        "backupInterval": 0,
        "backupRetention": 0,
        "trustCgnatIpAddresses": True
    }


@router.get("/api/v3/config/indexer")
async def get_config_indexer(client: MedusaClient = Depends(get_medusa_client)):
    config = await client.get_system_config()
    indexers = config.get("indexers", {}).get("indexers", {})
    return [
        {"id": data.get("id"), "name": name, "enabled": data.get("enabled")}
        for name, data in indexers.items()
    ]

@router.get("/api/v3/config/downloadclient")
async def get_config_downloadclient(client: MedusaClient = Depends(get_medusa_client)):
    config = await client.get_system_config()
    clients = config.get("clients", {})
    # This might need refinement based on actual expected return structure
    return clients

@router.get("/api/v3/config/importlist")
async def get_config_importlist(client: MedusaClient = Depends(get_medusa_client)):
    # Import list is not clearly defined in the config example, returning empty list
    return []

@router.get("/api/v3/importlistexclusion/paged")
async def get_import_list_exclusions(page: int = Query(1), pageSize: int = Query(50)):
    return {
        "page": page,
        "pageSize": pageSize,
        "sortKey": None,
        "sortDirection": "default",
        "totalRecords": 1,
        "records": [
            {"id": 1, "tvdbId": 1, "title": None}
        ]
    }

@router.get("/api/v3/customfilter")
async def get_custom_filters():
    return [
        {
            "id": 1,
            "type": None,
            "label": None,
            "filters": [{}]
        }
    ]

@router.get("/api/v3/customformat")
async def get_custom_formats():
    return []

@router.get("/api/v3/remotepathmapping")
async def get_remote_path_mappings():
    return [
        {
            "id": 1,
            "host": None,
            "remotePath": None,
            "localPath": None
        }
    ]

@router.get("/api/v3/metadata")
async def get_metadata():
    return [
        {
            "id": 1,
            "name": None,
            "fields": [
                {
                    "order": 1,
                    "name": None,
                    "label": None,
                    "unit": None,
                    "helpText": None,
                    "helpTextWarning": None,
                    "helpLink": None,
                    "value": None,
                    "type": None,
                    "advanced": True,
                    "selectOptions": [
                        {"value": 1, "name": None, "order": 1, "hint": None}
                    ],
                    "selectOptionsProviderAction": None,
                    "section": None,
                    "hidden": None,
                    "privacy": "normal",
                    "placeholder": None,
                    "isFloat": True
                }
            ],
            "implementationName": None,
            "implementation": None,
            "configContract": None,
            "infoLink": None,
            "message": {"message": None, "type": "info"},
            "tags": [1],
            "presets": [],
            "enable": True
        }
    ]

@router.get("/api/v3/autotagging")
async def get_autotagging():
    return [
        {
            "id": 1,
            "name": None,
            "removeTagsAutomatically": True,
            "tags": [1],
            "specifications": [
                {
                    "id": 1,
                    "name": None,
                    "implementation": None,
                    "implementationName": None,
                    "negate": True,
                    "required": True,
                    "fields": [
                        {
                            "order": 1,
                            "name": None,
                            "label": None,
                            "unit": None,
                            "helpText": None,
                            "helpTextWarning": None,
                            "helpLink": None,
                            "value": None,
                            "type": None,
                            "advanced": True,
                            "selectOptions": [
                                {"value": 1, "name": None, "order": 1, "hint": None}
                            ],
                            "selectOptionsProviderAction": None,
                            "section": None,
                            "hidden": None,
                            "privacy": "normal",
                            "placeholder": None,
                            "isFloat": True
                        }
                    ]
                }
            ]
        }
    ]
