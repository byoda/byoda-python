# Data access control

The Pod controls access to the data for the services stored in the Pod based on access controls that
are defined in the service contract for each of the services. After evaluating the data requested by a client
against these access controls, the Pod may return no data or some or all of the requested data.

The access controls consist of one or more defined entities, with for each entity a list of actions that are
permitted. Each of the actions may support some specifiers that provide additional info on data may be used. The supported entities are:
- member: The membership in the Pod of the service, or, with other words, you; the owner of the pod
- service: The person or organization hosting the service
- network: someone that you have a network relation with. This entity supports two specifiers:
  - distance (integer, n>=1, default=1): some other member who you have a network path in your social graph with, with a maximum distance of 'n'
  - relation (string with regular expression, defaults to None): the relation with the members in your social graph must match this regular expression. If not specified, all relations are permitted access
- any_member: Any person who has joined the service
- anonymous: Anyone, regardless whether or not they provided credentials to authenticate their data request

The following actions are supported:
- read with specifier:
  - cache (int: seconds or string with "4h", "600s", "1d" etc., defaults to 14400 seconds): how long may the requesting entity cache the data
- update, no specifiers
- delete: delete the value of the key
- append: add an entry to an array

The access controls can only be defined for the 'properties' defined for the 'jsonschema' in the service contract and not for the data structures defined under the '$defs' section
- (not yet supported in the pod) search: (only applies to simple values, not to objects or arrays): Search an array for object with a key containing the specified value. Specifiers:
  - type: (string). The values depend on the type of field the search action is specified:
    - for string values:
      - "full case-sensitive"
      - "full case-insensitive"
      - "partial case-sensitive"
      - "partial case-insensitive"
      - "regex"
    - for number values:
      - "="
      - ">"
      - ">="
      - "<"
      - "<="
      - "range"
    - for strings with dates:
      - "="
      - ">"
      - ">="
      - "<"
      - "<="
      - "between"
    - for booleans:
      - "is"