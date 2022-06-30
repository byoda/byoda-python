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
query ($filters: networkLinkInputFilter) {
    network_links_connection(filters: $filters) {
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
mutation ($filters: networkLinkInputFilter!, $relation: String!) {
    update_network_links(filters: $filters, relation: $relation) {
        member_id relation timestamp
    }
}
'''

DELETE_FROM_NETWORK_WITH_FILTER = '''
mutation ($filters: networkLinkInputFilter!) {
    delete_from_network_links(filters: $filters) {
        relation
        member_id
        timestamp
    }
}
'''

# Network Assets refer to Asset objects so we use assetInputFilter
QUERY_NETWORK_ASSETS = '''
query ($filters: assetInputFilter, $first: Int, $after: String, $depth: Int,
      $relations: [String!]) {
    network_assets_connection(
        filters: $filters, first: $first, after: $after, depth: $depth,
        relations: $relations) {
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

# Network Assets refer to Asset objects so we use assetInputFilter
UPDATE_NETWORK_ASSETS = '''
mutation (
        $filters: assetInputFilter!, $timestamp: DateTime,
        $asset_type: String, $asset_id: UUID, $creator: String,
        $created: DateTime, $title: String, $subject: String,
        $contents: String, $keywords: [String!]) {
    update_network_assets (
        filters: $filters, timestamp: $timestamp,
        asset_type: $asset_type, asset_id: $asset_id, creator: $creator,
        created: $created, title: $title, subject: $subject,
        contents: $contents, keywords: $keywords
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
