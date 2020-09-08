import json
from utilities.launcher import accept_delegation_task_chunk


def lambda_handler(event, context):
    """ This is the true entry point from lambda invocation.
        It is convenient to place this entry point in main.py
        rather than a subsidiary module, because the import
        order will be the same whether the call is invoked in
        lambdas or locally. At least that is the theory.
    """

    task_args       = event['task_args']
    request_id      = context.aws_request_id
    
    return accept_delegation_task_chunk(request_id, task_args)


class context:
    aws_request_id = 'FakeRequestID'


if __name__ == "__main__":

    context.aws_request_id = 'FakeRequestID'
    with open(r'./input_files/bif_lambda_task_args.json') as json_file:
        event = json.load(json_file)
        lambda_handler(event, context)


