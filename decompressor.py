#!/usr/bin/python3.6
# Copyright (c) 2019 FRC Team 1678: Citrus Circuits
"""Decompresses objective and subjective match collection QR codes"""
# External imports
import enum
import yaml
# Internal imports
import utils


class QRType(enum.Enum):
    """Enum that stores QR types"""
    OBJECTIVE = 0
    SUBJECTIVE = 1


def _get_data_fields(section):
    """Get data fields of a section in the schema

    Filters out all entries beginning with '_' as they contain information about the
    (de)compression process, not what data fields should be present.
    """
    data_fields = set()
    for field in SCHEMA[section]:
        # Filter out '_' at start of entry
        if not field.startswith('_'):
            data_fields.add(field)
    return data_fields


def convert_data_type(value, type_, name=None):
    """Convert from QR string representation to database data type"""
    # Enums are stored as int in the database
    if type_ == 'int':
        return int(value)
    if type_ == 'float':
        return float(value)
    if type_ == 'bool':
        return utils.get_bool(value)
    if type_ == 'str':
        return value  # Value is already a str
    if type_ == 'Enum':
        return get_decompressed_name(value, name)
    raise ValueError(f'Type {type_} not recognized')


def get_decompressed_name(compressed_name, section):
    """Returns decompressed variable name from schema

    compressed_name: str - Compressed variable name within QR code
    section: str - Section of schema that name comes from
    """
    for key, value in SCHEMA[section].items():
        if isinstance(value, list):
            if value[0] == compressed_name:
                return key
        else:
            if value == compressed_name:
                return key
    raise ValueError(f'Retrieving Variable Name {compressed_name} from {section} failed.')


def get_decompressed_type(name, section):
    """Returns server-side data type from schema

    name: str - Decompressed variable name within Schema
    section: str - Section of schema that name comes from
    """
    # Type all items after the first item
    type_ = SCHEMA[section][name][1:]
    # Detect special case of data type being a list
    if len(type_) > 1:
        return type_  # Returns list of the type (list) and the type of data stored in the list
    return type_[0]  # Return the type of the value


def decompress_data(data, section):
    """Decompress (split) data given the section of the QR it came from

    This matches compressed data names to actual variable names. It treats embedded dictionaries as
    special cases, a parsing function needs to be written for each (e.g. timeline).
    """
    decompressed_data = {}
    # Iterate through data
    for data_field in data:
        compressed_name = data_field[0]  # Compressed name is always first character
        value = data_field[1:]  # Actual data value is everything after the first character
        # Get uncompressed name and the target data type
        uncompressed_name = get_decompressed_name(compressed_name, section)
        uncompressed_type = get_decompressed_type(uncompressed_name, section)
        # Detect special cases in typing (e.g. value is list)
        if isinstance(uncompressed_type, list):
            # If second data type is dictionary, it should be handled separately
            if 'dict' in uncompressed_type:
                # Decompress timeline
                if uncompressed_name == 'timeline':
                    typed_value = decompress_timeline(value)
                # Value is not one of the currently known dictionaries
                else:
                    raise NotImplementedError(
                        f'Decompression of {uncompressed_name} as a dict not supported.')

            else:  # Normal list, split by internal separator
                value = value.split(SCHEMA[section]['_separator_internal'])
                typed_value = []
                # Convert all values in list to schema specified types
                for item in value:
                    # Name does not need to be specified because lists will not contain enums
                    typed_value.append(convert_data_type(item, uncompressed_type[-1]))

        else:  # Normal data type
            typed_value = convert_data_type(value, uncompressed_type, uncompressed_name)
        decompressed_data[uncompressed_name] = typed_value
    return decompressed_data


def decompress_generic_qr(data):
    """Decompress generic section of QR or raise error if schema is outdated"""
    # Split data by separator specified in schema
    data = data.split(SCHEMA['generic_data']['_separator'])
    for entry in data:
        if entry[0] == 'A':
            schema_version = int(entry[1:])
            if schema_version != SCHEMA['schema_file']['version']:
                raise LookupError(f'QR Schema (v{schema_version}) does not match Server version')
    return decompress_data(data, 'generic_data')


def get_timeline_info():
    """Loads information about timeline fields"""
    timeline_fields = []
    for field, field_list in SCHEMA['timeline'].items():
        field_data = {
            'name': field,
            'length': field_list[0],
            'type': field_list[1],
            'position': field_list[2],
        }
        timeline_fields.append(field_data)
    # Sort timeline_fields by the position they appear in
    timeline_fields.sort(key=lambda x: x['position'])
    return timeline_fields


def decompress_timeline(data):
    """Decompress the timeline based on schema"""
    decompressed_timeline = []  # Timeline is a list of dictionaries
    # Return empty list if timeline is empty
    if data == '':
        return decompressed_timeline
    timeline_length = sum([entry['length'] for entry in _TIMELINE_FIELDS])
    # Split into list of actions. Each action is a string of length timeline_length
    timeline_actions = [data[i:i + timeline_length] for i in range(0, len(data), timeline_length)]
    for action in timeline_actions:
        decompressed_action = dict()
        current_position = 0
        for entry in _TIMELINE_FIELDS:
            # Get untyped value by slicing action string from current position to next position
            next_position = current_position + entry['length']
            untyped_value = action[current_position:next_position]
            # Set action value to the converted data type
            decompressed_action[entry['name']] = convert_data_type(
                untyped_value, entry['type'], entry['name'])
            current_position = next_position
        decompressed_timeline.append(decompressed_action)
    return decompressed_timeline


def get_qr_type(first_char):
    """Returns the qr type from QRType enum based on first character."""
    if first_char == SCHEMA['objective_tim']['_start_character']:
        return QRType.OBJECTIVE
    if first_char == SCHEMA['subjective_aim']['_start_character']:
        return QRType.SUBJECTIVE
    raise ValueError(f'QR type unknown - Invalid first character for QR: {first_char}')


def decompress_single_qr(qr_data, qr_type):
    """Decompress a full QR"""
    # Split into generic data and objective/subjective data
    qr_data = qr_data.split(SCHEMA['generic_data']['_section_separator'])
    # Generic QR is first section of QR
    decompressed_data = decompress_generic_qr(qr_data[0])
    # Decompress subjective QR
    if qr_type == QRType.SUBJECTIVE:
        subjective_data = qr_data[1].split(SCHEMA['subjective_aim']['_separator'])
        decompressed_data.update(decompress_data(subjective_data, 'subjective_aim'))
        if set(decompressed_data.keys()) != SUBJECTIVE_QR_FIELDS:
            raise ValueError('QR missing data fields')
    elif qr_type == QRType.OBJECTIVE:  # Decompress objective QR
        objective_data = qr_data[1].split(SCHEMA['objective_tim']['_separator'])
        decompressed_data.update(decompress_data(objective_data, 'objective_tim'))
        if set(decompressed_data.keys()) != OBJECTIVE_QR_FIELDS:
            raise ValueError('QR missing data fields')
    return decompressed_data


def decompress_qrs(split_qrs):
    """Decompresses a list of QRs. Returns dict of decompressed QRs split by type."""
    output = {
        'unconsolidated_obj_tim': [],
        'subj_aim': []
    }
    for qr in split_qrs:
        qr_type = utils.catch_function_errors(get_qr_type, qr[0])
        if qr_type is None:
            continue
        # Remove identification character
        qr = qr[1:]
        decompressed_qr = utils.catch_function_errors(decompress_single_qr, qr, qr_type)
        if decompressed_qr is None:
            continue
        if qr_type == QRType.OBJECTIVE:
            output['unconsolidated_obj_tim'].append(decompressed_qr)
        elif qr_type == QRType.SUBJECTIVE:
            output['subj_aim'].append(decompressed_qr)
    return output


# Load latest match collection compression QR code schema
with open(utils.create_file_path('schema/match_collection_qr_schema.yml', False),
          'r') as file:
    # Specify loader to avoid warnings about default loader
    SCHEMA = yaml.load(file, yaml.Loader)

_GENERIC_DATA_FIELDS = _get_data_fields('generic_data')
OBJECTIVE_QR_FIELDS = _GENERIC_DATA_FIELDS.union(_get_data_fields('objective_tim'))
SUBJECTIVE_QR_FIELDS = _GENERIC_DATA_FIELDS.union(_get_data_fields('subjective_aim'))
_TIMELINE_FIELDS = get_timeline_info()
