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
mutation(
        $given_name: String!, $additional_names: String,
        $family_name: String!, $email: String!,
        $homepage_url: String, $avatar_url: String) {
    mutate_person(
        given_name: $given_name,
        additional_names: $additional_names,
        family_name: $family_name,
        email: $email,
        homepage_url: $homepage_url,
        avatar_url: $avatar_url
    ) {
        given_name
        additional_names
        family_name
        email
        homepage_url
        avatar_url
    }
}
'''

QUERY_NETWORK = '''
query {
    network_links_connection {
        total_count
        edges {
            cursor
            network_link {
                relation
                member_id
                timestamp
            }
        }
        page_info {
            end_cursor
            has_next_page
        }
    }
}
'''

QUERY_NETWORK_WITH_FILTER = '''
query {{
    network_links_connection(filters: {{ {field}: {{ {cmp}: "{value}" }} }}) {{
        total_count
        edges {{
            cursor
            network_link {{
                relation
                member_id
                timestamp
            }}
        }}
        page_info {{
            end_cursor
            has_next_page
        }}
    }}
}}
'''

APPEND_NETWORK = '''
mutation ($member_id: UUID!, $relation: String!, $timestamp: DateTime!) {
    append_network_links (
        member_id: $member_id,
        relation: $relation,
        timestamp: $timestamp
    ) {
        member_id relation timestamp
    }
}
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

QUERY_NETWORK_ASSETS = '''
query ($first: Int, $after: String, $depth: Int, $relations: [String!]) {
    network_assets_connection(
        first: $first, after: $after, depth: $depth, relations: $relations
    ) {
        total_count
        edges {
            cursor
            asset {
                timestamp
                asset_type
                asset_id
                title
            }
        }
        page_info {
            end_cursor
            has_next_page
        }
    }
}
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
mutation (
        $timestamp: DateTime!, $asset_type: String!, $asset_id: UUID!,
        $creator: String, $created: DateTime, $title: String, $subject: String,
        $contents: String, $keywords: [String!]) {
    append_network_assets (
        timestamp: $timestamp,
        asset_type: $asset_type,
        asset_id: $asset_id,
        creator: $creator,
        created: $created,
        title: $title,
        subject: $subject,
        contents: $contents,
        keywords: $keywords
    ) {
        timestamp
        asset_type
        asset_id
        creator
        created
        title
        subject
        contents
        keywords
    }
}
'''
