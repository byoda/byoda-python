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
        additional_names: "",
        family_name: "{family_name}",
        email: "{email}",
        homepage_url: "https://some.place/",
        avatar_url: "https://some.place/avatar"
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
