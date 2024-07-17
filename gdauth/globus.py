import os
import pathlib
import time
import globus_sdk
import numpy as np

from gdauth import log

def refresh_globus_token(app_uuid):
    """
    Verify that existing Globus token exists and it is still valid, 
    if not creates & saves or refresh & save the globus token. 
    The token is valid for 48h.

    Parameters
    ----------
    app_uuid : App UUID 
      
    """

    globus_token_file=os.path.join(str(pathlib.Path.home()), 'token.npy')

    try:
        token_response = np.load(globus_token_file, allow_pickle='TRUE').item()
    except FileNotFoundError:
        log.error('Globus token is missing. Creating one')
        # Creating new token
        # --------------------------------------------
        client = globus_sdk.NativeAppAuthClient(app_uuid)
        client.oauth2_start_flow(refresh_tokens=True)

        log.warning('Please go to this URL and login: {0}'.format(client.oauth2_get_authorize_url()))

        get_input = getattr(__builtins__, 'raw_input', input)
        auth_code = get_input('Please enter the code you get after login here: ').strip() # pythn 3
        # auth_code = raw_input('Please enter the code you get after login here: ').strip() # python 2.7
        token_response = client.oauth2_exchange_code_for_tokens(auth_code)
        # --------------------------------------------
        np.save(globus_token_file, token_response) 

    # let's get stuff for the Globus Transfer service
    globus_transfer_data = token_response.by_resource_server['transfer.api.globus.org']
    # the refresh token and access token, often abbr. as RT and AT
    transfer_rt = globus_transfer_data['refresh_token']
    transfer_at = globus_transfer_data['access_token']
    expires_at_s = globus_transfer_data['expires_at_seconds']

    globus_token_life = expires_at_s - time.time()
    if (globus_token_life < 0):
        # Creating new token
        # --------------------------------------------
        globus_app_id = app_uuid
        client = globus_sdk.NativeAppAuthClient(globus_app_id)
        client.oauth2_start_flow(refresh_tokens=True)

        log.warning('Please go to this URL and login: {0}'.format(client.oauth2_get_authorize_url()))

        get_input = getattr(__builtins__, 'raw_input', input)
        auth_code = get_input('Please enter the code you get after login here: ').strip()
        token_response = client.oauth2_exchange_code_for_tokens(auth_code)
        # --------------------------------------------
        np.save(globus_token_file, token_response) 

    return token_response


def create_clients(app_uuid):
    """
    Create authorize and transfer clients

    Parameters
    ----------
    globus_app_id : App UUID 

    Returns
    -------
    ac : Authorize client
    tc : Transfer client
      
    """

    token_response = refresh_globus_token(app_uuid)
    # let's get stuff for the Globus Transfer service
    globus_transfer_data = token_response.by_resource_server['transfer.api.globus.org']
    # the refresh token and access token, often abbr. as RT and AT
    transfer_rt = globus_transfer_data['refresh_token']
    transfer_at = globus_transfer_data['access_token']
    expires_at_s = globus_transfer_data['expires_at_seconds']

    globus_token_life = expires_at_s - time.time()
    log.warning("Globus access token will expire in %2.2f hours", (globus_token_life/3600))

    client = globus_sdk.NativeAppAuthClient(app_uuid)
    client.oauth2_start_flow(refresh_tokens=True)
    # Now we've got the data we need we set the authorizer
    authorizer = globus_sdk.RefreshTokenAuthorizer(transfer_rt, client, access_token=transfer_at, expires_at=expires_at_s)

    ac = globus_sdk.AuthClient(authorizer=authorizer)
    tc = globus_sdk.TransferClient(authorizer=authorizer)

    return ac, tc


def create_dir(directory, # Subdirectory name under top to be created
           app_uuid,  # Globus App / Client UUID
           ep_uuid):  # Endpoint UUID

    dir_path = '/' + str(directory) + '/'
    ac, tc = create_clients(app_uuid)
    try:
        response = tc.operation_mkdir(ep_uuid, path=dir_path)
        log.info('*** Created folder: %s' % dir_path)
        log.info(create_folder_link(directory, app_uuid, ep_uuid))

        return True
    except globus_sdk.TransferAPIError as e:
        log.warning(f"Transfer API Error: {e.code} - {e.message}")
        log.info(create_folder_link(directory, app_uuid, ep_uuid))
        # log.error(f"Details: {e.raw_text}")
        return True
    except:
        log.error('*** Unknow error')
        return False


def check_folder_exists(directory, app_uuid, ep_uuid):

    ac, tc = create_clients(app_uuid)

    try:
        tc.operation_ls(ep_uuid, path=directory)
        return True
    except globus_sdk.TransferAPIError as e:
        if e.code == 'ClientError.NotFound':
            return False
        else:
            raise e


def get_user_id(app_uuid, email):

    ac, tc = create_clients(app_uuid)

    # Get user id from user email
    r = ac.get_identities(usernames=email, provision=True)
    user_id = r['identities'][0]['id']

    return user_id


def share(directory,       # Subdirectory name under top to be created
          email,           # User email address
          app_uuid, # Globus App UUID
          ep_uuid          # Endpoint UUID
          ):         
    """
    Share an existing globus directory with a globus user. The user receives an email with the link to the folder.
    To add a custom message to the email edit the "notify message" field below
 
    Parameters
    ----------
    email       : email address of the user you want to share the globus directory with
    directory   : directory name to be shared
    ep_uuid     : end point UUID
    ac          : Access client
    tc          : Transfer client

    """


    if check_folder_exists(directory, app_uuid, ep_uuid):
        ac, tc = create_clients(app_uuid)
        user_id = get_user_id(app_uuid, email)

        dir_path = '/' + directory + '/'
        # Set access control and notify user
        rule_data = {
          'DATA_TYPE': 'access',
          'principal_type': 'identity',
          'principal': user_id,
          'path': dir_path,
          'permissions': 'r',
          'notify_email': email,
          'notify_message': "add here a custom meassage"
        }

        try: 
            response = tc.add_endpoint_acl_rule(ep_uuid, rule_data)
            log.info('*** Path %s has been shared with %s' % (dir_path, email))
            log.info(create_folder_link(directory, app_uuid, ep_uuid))
            return True
        except globus_sdk.TransferAPIError as e:
            log.error(f"Transfer API Error: {e.code} - {e.message}")
            return False
        except:
            log.warning('*** Path %s is already shared with %s' % (dir_path, email))
            return False
    else:
        log.error('%s does not exist' % directory)
        log.error('Run: python globus.py create --directory <directory name>')


def find_endpoints(app_uuid, show=False):
    """
    Show all end points

    Parameters
    ----------
    tc : Transfer client

    """

    ac, tc = create_clients(app_uuid)
    
    endpoints = {}
    if show:
        log.info('Show all endpoints shared and owned by my globus user credentials')
        log.info("*** Endpoints shared with me:")
        for ep in tc.endpoint_search(filter_scope="shared-with-me"):
            log.info("*** *** [{}] {}".format(ep["id"], ep["display_name"]))
        log.info("*** Endpoints owned with me:")
        for ep in tc.endpoint_search(filter_scope="my-endpoints"):
            log.info("*** *** [{}] {}".format(ep["id"], ep["display_name"]))
        log.info("*** Endpoints shared by me:")
        for ep in tc.endpoint_search(filter_scope="shared-by-me"):
            log.info("*** *** [{}] {}".format(ep["id"], ep["display_name"]))
            endpoints[ep['display_name']] = ep['id']
    else:
        for ep in tc.endpoint_search(filter_scope="shared-by-me"):
            endpoints[ep['display_name']] = ep['id']

    return endpoints


def create_folder_link(directory, app_uuid, ep_uuid):

    ac, tc = create_clients(app_uuid)

    url = 'https://app.globus.org/file-manager?&origin_id='+ep_uuid+'&origin_path=/'+str(directory) #+'/&add_identity='+user_id

    return url


def create_links(directory, app_uuid, ep_uuid):

    file_links   = []
    folder_links = []

    ac, tc = create_clients(app_uuid)
    files, folders  = find_files(directory, app_uuid, ep_uuid)

    for file_name in files:
        file_links.append('https://' + tc.get_endpoint(ep_uuid)['tlsftp_server'][9:-4] + '/' + directory + '/' + file_name)
    for folder in folders:
        folder_links.append('https://app.globus.org/file-manager?&origin_id=' + ep_uuid + '&origin_path=/' + directory+ '/' + folder) #+'/&add_identity='+user_id)

    return file_links, folder_links


def find_endpoint_uuid(app_uuid, ep_name):

    ep_uuid = None
    # Ask the Globus server to show all end points it has access to
    end_points = find_endpoints(app_uuid)

    if ep_name in end_points:
        ep_uuid = end_points[ep_name]
    else:
        log.error('%s endpoint does not exists' % ep_name)
        log.error('Select one of this endpoints:')
        for key, value in end_points.items():
            log.error('*** *** %s' % key)

    return ep_uuid

    
def find_files(directory, app_uuid, ep_uuid):

    ac, tc = create_clients(app_uuid)
    response = tc.operation_ls(ep_uuid, path=directory)
    
    files   = []
    folders = []
    for item in response['DATA']:
        log.info('directory %s contains %s: %s' % (directory, item['type'], item['name']))
        if item['type'] == 'file':
            files.append(item['name'])
        if item['type'] == 'dir':
            folders.append(item['name'])

    return files, folders