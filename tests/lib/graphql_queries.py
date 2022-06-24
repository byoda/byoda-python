'''
GraphQL queries used by test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

QUERY_PERSON = '''
query {
    person {
        given_name
        additional_names
        family_name
        email
        homepage_url
        avatar_url
    }
}
'''

MUTATE_PERSON = '''
mutation {{
    mutate_person(
        given_name: "{given_name}",
        additional_names: "{additional_names}",
        family_name: "{family_name}",
        email: "{email}",
        homepage_url: "{homepage_url}",
        avatar_url: "{avatar_url}"
    ) {{
        given_name
        additional_names
        family_name
        email
        homepage_url
        avatar_url
    }}
}}
'''

QUERY_NETWORK = '''
query {
    network_links {
        relation
        member_id
        timestamp
    }
}
'''

QUERY_NETWORK_WITH_FILTER = '''
query {{
    network_links(filters: {{ {field}: {{ {cmp}: "{value}" }} }}) {{
        relation
        member_id
        timestamp
    }}
}}
'''

APPEND_NETWORK = '''
mutation {{
    append_network_links (
        member_id: "{uuid}",
        relation: "{relation}",
        timestamp: "{timestamp}"
    ) {{
        member_id relation timestamp
    }}
}}
'''

UPDATE_NETWORK_RELATION = '''
mutation {{
    update_network_links (
        filters: {{ {field}: {{ {cmp}: "{value}" }} }},
        relation: "{relation}",
    ) {{
        member_id relation timestamp
    }}
}}
'''

DELETE_FROM_NETWORK_WITH_FILTER = '''
mutation {{
    delete_from_network_links(filters: {{ {field}: {{ {cmp}: "{value}" }} }}) {{
        relation
        member_id
        timestamp
    }}
}}
'''

UPDATE_NETWORK_ASSETS = '''
mutation {{
    update_network_assets (
        filters: {{ {field}: {{ {cmp}: "{value}" }} }},
        contents: "{contents}",
        keywords: {keywords}
    ) {{
        timestamp
        asset_type
        asset_id
        creator
        created
        title
        subject
        contents
        keywords
    }}
}}
'''
APPEND_NETWORK_ASSETS = '''
mutation {{
    append_network_assets (
        timestamp: "{timestamp}",
        asset_type: "{asset_type}",
        asset_id: "{asset_id}",
        creator: "{creator}",
        created: "{created}",
        title: "{title}",
        subject: "{subject}",
        contents: "{contents}",
        keywords: {keywords}
    ) {{
        timestamp
        asset_type
        asset_id
        creator
        created
        title
        subject
        contents
        keywords
    }}
}}
'''
