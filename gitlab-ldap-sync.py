#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gitlab
import sys
import json
import ldap
import ldap.asyncsearch
import logging


if __name__ == "__main__":
    print('Initializing gitlab-ldap-sync.')
    config = None
    with open('config.json') as f:
        config = json.load(f)
    ldap_config = config['ldap']
    gitlab_config = config['gitlab']
    if config is not None:
        print('Done.')
        print('Updating logger configuration')
        if not gitlab_config['group_visibility']:
            gitlab_config['group_visibility'] = 'private'
        log_option = {
            'format': '[%(asctime)s] [%(levelname)s] %(message)s'
        }
        if config['log']:
            log_option['filename'] = config['log']
        if config['log_level']:
            log_option['level'] = getattr(logging, str(config['log_level']).upper())
        logging.basicConfig(**log_option)

        print('Done.')
        logging.info('Connecting to GitLab')
        if gitlab_config['api']:
            gl = None
            if not gitlab_config['private_token'] and not gitlab_config['oauth_token']:
                logging.error('You should set at least one auth information in config.json, aborting.')
            elif gitlab_config['private_token'] and gitlab_config['oauth_token']:
                logging.error('You should set at most one auth information in config.json, aborting.')
            else:
                if gitlab_config['private_token']:
                    gl = gitlab.Gitlab(url=gitlab_config['api'], private_token=gitlab_config['private_token'], ssl_verify=gitlab_config['ssl_verify'])
                elif gitlab_config['oauth_token']:
                    gl = gitlab.Gitlab(url=gitlab_config['api'], oauth_token=gitlab_config['oauth_token'], ssl_verify=gitlab_config['ssl_verify'])
                else:
                    gl = None
                if gl is None:
                    logging.error('Cannot create gitlab object, aborting.')
                    sys.exit(1)
            gl.auth()
            logging.info('Done.')

            logging.info('Connecting to LDAP')
            if not ldap_config['url']:
                logging.error('You should configure LDAP in config.json')
                sys.exit(1)

            try:
                l = ldap.initialize(uri=ldap_config['url'])
                l.simple_bind_s(ldap_config['bind_dn'], ldap_config['password'])
            except:
                logging.error('Error while connecting')
                sys.exit(1)

            logging.info('Done.')

            logging.info('Getting all groups from GitLab.')
            gitlab_groups = []
            gitlab_groups_names = []
            for group in gl.groups.list(all=True):
                gitlab_groups_names.append(group.full_name)
                gitlab_group = {"name": group.full_name, "members": []}
                for member in group.members.list(all=True):
                    user = gl.users.get(member.id)
                    print(user)
                    identities = None
                    if len(user.identities) > 0:
                        identities = user.identities[0]['extern_uid']
                    gitlab_group['members'].append({
                        'username': user.username,
                        'name': user.name,
                        'identities': identities,
                        'email': user.email
                    })
                gitlab_groups.append(gitlab_group)

            logging.info('Done.')

            logging.info('Getting all groups from LDAP.')
            ldap_groups = []
            ldap_groups_names = []
            group_class = ldap_config["group_class"]
            if not group_class:
                group_class = "groupOfUniqueNames"
            filterstr = "objectClass="+group_class
            if config['ldap']['group_prefix']:
                filterstr = '(&(objectClass=group)(cn=%s*))' % ldap_config['group_prefix']
            print(filterstr)
            # filterstr = "objectClass="+ldap_config["group_filter"]
            # filterstr=None
            group_alias = ldap_config["group_alias"]
            name = group_alias["name"]
            member = group_alias["member"]
            resutls = l.search_s(base=ldap_config['groups_base_dn'], scope=ldap.SCOPE_SUBTREE, filterstr=filterstr)

            for group_dn, group_data in resutls:
                group_name = group_data[member].decode()
                group_member = [i.decode() for i in group_data[member]]
                ldap_groups_names.append(group_member)
                ldap_group = {"name": group_member, "members": []}
                
                if gitlab_config['add_description'] and 'description' in group_data:
                    ldap_group.update({"description": group_data['description'][0].decode()})
                if 'member' in group_data:
                    for member in group_data['member']:
                        member = member.decode()
                        for user_dn, user_data in l.search_s(base=ldap_config['users_base_dn'],
                                                             scope=ldap.SCOPE_SUBTREE,
                                                             filterstr='(&(|(distinguishedName=%s)(dn=%s))(objectClass=user)%s)' % (
                                member, member, ldap_config['user_filter']),
                                attrlist=['uid', 'sAMAccountName', 'mail', 'displayName']):
                            if 'sAMAccountName' in user_data:
                                username = user_data['sAMAccountName'][0].decode()
                            else:
                                username = user_data['uid'][0].decode()
                            ldap_group['members'].append({
                                'username': username,
                                'name': user_data['displayName'][0].decode(),
                                'identities': str(member).lower(),
                                'email': user_data['mail'][0].decode()
                            })
                ldap_groups.append(ldap_group)
            logging.info('Done.')

            logging.info('Groups currently in GitLab : %s' % str.join(', ', gitlab_groups_names))
            logging.info('Groups currently in LDAP : %s' % str.join(', ', ldap_groups_names))

            logging.info('Syncing Groups from LDAP.')

            for l_group in ldap_groups:
                logging.info('Working on group %s ...' % l_group['name'])
                if l_group['name'] not in gitlab_groups_names:
                    logging.info('|- Group not existing in GitLab, creating.')
                    gitlab_group = {'name': l_group['name'], 'path': l_group['name'], 'visibility': gitlab_config['group_visibility']}
                    if gitlab_config['add_description'] and 'description' in l_group:
                        gitlab_group.update({'description': l_group['description']})
                    try:
                        g = gl.groups.create(gitlab_group)
                        g.save()
                        gitlab_groups.append({'members': [], 'name': l_group['name']})
                        gitlab_groups_names.append(l_group['name'])
                    except Exception as e:
                        logging.error('Creating group %s failed: %s' % (l_group['name'], e))
                        # Skip next steps due to group could not be created
                        continue
                else:
                    logging.info('|- Group already exist in GitLab, skiping creation.')

                logging.info('|- Working on group\'s members.')
                for l_member in l_group['members']:
                    if l_member not in gitlab_groups[gitlab_groups_names.index(l_group['name'])]['members']:
                        logging.info('|  |- User %s is member in LDAP but not in GitLab, updating GitLab.' % l_member['name'])
                        g = [group for group in gl.groups.list(search=l_group['name']) if group.name == l_group['name']][0]
                        g.save()
                        u = gl.users.list(search=l_member['username'])
                        if len(u) > 0:
                            u = u[0]
                            if u not in g.members.list(all=True):
                                g.members.create({'user_id': u.id, 'access_level': gitlab.DEVELOPER_ACCESS})
                            g.save()
                        else:
                            if gitlab_config['create_user']:
                                logging.info('|  |- User %s does not exist in gitlab, creating.' % l_member['name'])
                                try:
                                    u = gl.users.create({
                                        'email': l_member['email'],
                                        'name': l_member['name'],
                                        'username': l_member['username'],
                                        'extern_uid': l_member['identities'],
                                        'provider': gitlab_config['ldap_provider'],
                                        'password': 'pouetpouet'
                                    })
                                except gitlab.exceptions as e:
                                    if e.response_code == '409':
                                        u = gl.users.create({
                                            'email': l_member['email'].replace('@', '+gl-%s@' % l_member['username']),
                                            'name': l_member['name'],
                                            'username': l_member['username'],
                                            'extern_uid': l_member['identities'],
                                            'provider': gitlab_config['ldap_provider'],
                                            'password': 'pouetpouet'
                                        })
                                g.members.create({'user_id': u.id, 'access_level': gitlab.DEVELOPER_ACCESS})
                                g.save()
                            else:
                                logging.info('|  |- User %s does not exist in gitlab, skipping.' % l_member['name'])
                    else:
                        logging.info('|  |- User %s already in gitlab group, skipping.' % l_member['name'])
                logging.info('Done.')

            logging.info('Done.')

            logging.info('Cleaning membership of LDAP Groups')

            for g_group in gitlab_groups:
                logging.info('Working on group %s ...' % g_group['name'])
                if g_group['name'] in ldap_groups_names:
                    logging.info('|- Working on group\'s members.')
                    for g_member in g_group['members']:
                        if g_member not in ldap_groups[ldap_groups_names.index(g_group['name'])]['members']:
                            if str(ldap_config['users_base_dn']).lower() not in g_member['identities']:
                                logging.info('|  |- Not a LDAP user, skipping.')
                            else:
                                logging.info('|  |- User %s no longer in LDAP Group, removing.' % g_member['name'])
                                g = [group for group in gl.groups.list(search=g_group['name']) if group.name == g_group['name']][0]
                                u = gl.users.list(search=g_member['username'])[0]
                                if u is not None:
                                    g.members.delete(u.id)
                                    g.save()
                        else:
                            logging.info('|  |- User %s still in LDAP Group, skipping.' % g_member['name'])
                    logging.info('|- Done.')
                else:
                    logging.info('|- Not a LDAP group, skipping.')
                logging.info('Done')
        else:
            logging.error('GitLab API is empty, aborting.')
            sys.exit(1)
    else:
        print('Could not load config.json, check if the file is present.')
        print('Aborting.')
        sys.exit(1)
