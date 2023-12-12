import pandas as pd

def dynamodb_to_dataframe(operation, **query_args):
    df_list = []

    response = operation(**query_args)
    while True:
        df_list.append(pd.DataFrame(response['Items']))
        if 'LastEvaluatedKey' in response:
            query_args['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = operation(**query_args)
        else:
            if len(df_list) == 0:
                return pd.DataFrame()
            else:
                return pd.concat(df_list)
