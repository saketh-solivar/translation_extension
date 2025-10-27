def find_session_row(rows, session_id):
    """Finds the 1-based row number for a given session_id"""
    for i, row in enumerate(rows):
        if len(row) > 2 and row[2] == session_id:
            return i + 1  # Sheets API uses 1-based index
    return None

def get_prompt_column_index(headers, prompt_index):
    """Finds column index of Response{prompt_index}"""
    header = f"Response{prompt_index}"
    if header in headers:
        return headers.index(header)
    raise ValueError(f"{header} not found in headers.")

def get_aqg_column_index(headers, prompt_index, additional_index):
    """Finds the AQGResponseN column for given prompt and AQG number"""
    # First, locate where Response{prompt_index} starts
    prompt_header = f"Response{prompt_index}"
    if prompt_header not in headers:
        raise ValueError(f"{prompt_header} not found in headers.")

    start_index = headers.index(prompt_header)
    aqg_count = 0

    for i in range(start_index, len(headers)):
        if headers[i].startswith("AQGResponse"):
            aqg_count += 1
            if aqg_count == additional_index:
                return i

    raise ValueError(f"AQGResponse {additional_index} for Prompt {prompt_index} not found.")

def get_question_column_index(headers, question_index):
    """Finds the column index of QResponseN"""
    header = f"QResponse{question_index}"
    if header in headers:
        return headers.index(header)
    raise ValueError(f"{header} not found in headers.")

def convert_to_column_letter(col_index):
    """Converts 0-based index to Excel A1 column letter"""
    result = ""
    col_index += 1
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result
