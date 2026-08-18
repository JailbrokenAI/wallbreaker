import re
import warnings


def parse_meta_response(response, total_num, unsafe_num):
    """
    Parses the response from the LLM to extract the input, X(input), and Y(X(input)) pairs.
    Returns a list of dictionaries with the parsed data.
    """
    if not isinstance(response, str):
        warnings.warn("Response is not a string, returning empty list.")
        return []
        
    patterns = [
        r'Input:\s*(.*?)\s*X\(input\):\s*(.*?)\s*Y\(X\(input\)\):\s*(Yes|No)',
        r'\**Input\**:\s*(.*?)\s*\**X\(input\)\**:\s*(.*?)\s*\**Y\(X\(input\)\)\**:\s*(Yes|No)',  
        r'\**Input:\**\s*(.*?)\s*\**X\(input\):\**\s*(.*?)\s*\**Y\(X\(input\)\):\**\s*(Yes|No)', 
        r'\"*Input\"*:\s*(.*?)\s*\"*X\(input\)\"*:\s*(.*?)\s*\"*Y\(X\(input\)\)\"*:\s*(Yes|No)', 
    ]
    for pattern in patterns:
        matches = re.findall(pattern, response, re.DOTALL)
        if len(matches) > 0:
            break

    if len(matches) != total_num:
        warnings.warn(f"Expected {total_num} examples, but found {len(matches)}.")

    parsed_data = []
    for match in matches:
        input_str, x_input, y_x_input = match
        parsed_data.append({
            'input': input_str.strip(),
            'X(input)': x_input.strip(),
            'Y(X(input))': y_x_input.strip()
        })

    return parsed_data


def parse_gpt_judge(response):
    """ Parse the GPT judge response to extract the score. """
    response = response.strip().lower()
    if response.isdigit():
        return int(response)
    else:
        if response.startswith('#thescore:'):
            assert response.split()[1].isdigit()
            return int(response.split()[1])
        elif response.startswith('#'):
            assert response.split('#')[1].isdigit()
            return int(response.split('#')[1])

