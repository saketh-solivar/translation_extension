def find_session_row(rows, session_id):
    """Finds the 1-based row number for a given session_id"""
    for i, row in enumerate(rows):
        if len(row) > 2 and row[2] == session_id:
            return i + 1  # Sheets API uses 1-based index
    return None

def get_prompt_column_index(headers, prompt_index):
    # Convert 0-based JS index → 1-based sheet column
    column_number = prompt_index + 1
    column_name = f"Response{column_number}"

    if column_name not in headers:
        raise ValueError(f"{column_name} not found in headers.")

    return headers.index(column_name) + 1

def get_aqg_column_index(headers, prompt_index, additional_index):
    """
    Finds the AQGResponse_P{prompt}_{aqg} column.
    Converts 0-based indices from frontend to 1-based sheet columns.
    """

    prompt_number = prompt_index + 1
    aqg_number = additional_index + 1

    target_header = f"AQGResponse_P{prompt_number}_{aqg_number}"

    if target_header not in headers:
        raise ValueError(f"{target_header} not found in headers.")

    return headers.index(target_header) + 1

def get_question_column_index(headers, question_index):
    """
    Finds the QResponseN column.
    Converts 0-based index to 1-based.
    """

    question_number = question_index + 1
    header = f"QResponse{question_number}"

    if header not in headers:
        raise ValueError(f"{header} not found in headers.")

    return headers.index(header) + 1

def convert_to_column_letter(col_index):
    """Converts 0-based index to Excel A1 column letter"""
    result = ""
    col_index += 1
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result
