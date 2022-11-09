#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from MyGitlab import *
from MyLDAP import *


def ldap_user_to_gitlab(ldap_user_attr: dict[int, Any], dn: str, ldap_provider='ldapmaiin') -> MyUser:
    user = MyUser(id=-1,
                  username=ldap_user_attr['uid'],
                  name=ldap_user_attr['cn'],
                  email=ldap_user_attr['mail']
                  )
    user.ext_ID.uid = dn
    user.ext_ID.provider = ldap_provider
    return user


def create_group_in_gitlab_by_ldap(ldap_group: SimpleGroup, mygitlab: MyGitlab, new_group_visibility='private') -> int:
    group_info = GitlabGroup(name=ldap_group.name,
                             visibility=new_group_visibility
                             )
    if ldap_group.description is not None and ldap_group.description == '':
        group_info.description = ldap_group.description
    group_id = mygitlab.group_create(group_info)
    return group_id


def check_group_member_in_gitlab(ldap_group: SimpleGroup,
                                 mygitlab: MyGitlab,
                                 check_attr='extern_uid',
                                 new_group_visibility='private'
                                 ) -> tuple[bool, MyGroup, list[str]]:
    absense_items = ldap_group.members
    gitlab_group_names = mygitlab.mygroup_all.names
    create = ldap_group.name not in gitlab_group_names
    if create:
        group_id = create_group_in_gitlab_by_ldap(ldap_group=ldap_group,
                                                  mygitlab=mygitlab,
                                                  new_group_visibility=new_group_visibility
                                                  )
        gitlab_group = MyGroup(id=group_id, name=ldap_group.name)
    else:
        gitlab_group = mygitlab.mygroup_all.search(name=ldap_group.name)
        if gitlab_group is not None:
            absense_items = gitlab_group.check(red_list=ldap_group.member,
                                               attr=check_attr
                                               )[0]
    return create, gitlab_group, absense_items


def create_user_in_gitlab_by_ldap(dn: str, myldap: myLDAP, mygitlab: MyGitlab, ldap_provider='ldapmain') -> int:
    user_attr = myldap.user_info(dn=dn)
    user = ldap_user_to_gitlab(ldap_user_attr=user_attr,
                               ldap_provider=ldap_provider,
                               dn=dn
                               )
    return mygitlab.user_create(info=user)


def modify_group_user_into_gitlab_from_ldap(myldap: myLDAP,
                                            mygitlab: MyGitlab,
                                            ldap_group: SimpleGroup,
                                            create_user: bool = False,
                                            new_group_visibility='private',
                                            ldap_provider='ldapmain'
                                            ) -> None:
    results = check_group_member_in_gitlab(mygitlab=mygitlab,
                                           ldap_group=ldap_group,
                                           new_group_visibility=new_group_visibility
                                           )
    create, gitlab_group, absense_items = results
    for item in absense_items:
        user = mygitlab.myuser_all.search_by_ext_uid(extern_uid=item)
        if user is None and create_user:
            try:
                user_id = create_user_in_gitlab_by_ldap(dn=item,
                                                        myldap=myldap,
                                                        mygitlab=mygitlab,
                                                        ldap_provider=ldap_provider
                                                        )
            except:
                continue
        else:
            user_id = user.id
        if user_id is not None:
            mygitlab.group_add_member(group_info=gitlab_group, user_info=user, access_level=DEVELOPER_ACCESS)


def sync_exec(myldap: myLDAP,
              mygitlab: MyGitlab,
              ldap_group_list: SimpleGroupList,
              create_user: bool = False,
              new_group_visibility: str = 'private',
              ldap_provider: str = 'ldapmain'
              ) -> None:
    for ldap_group in ldap_group_list:
        try:
            modify_group_user_into_gitlab_from_ldap(myldap=myldap,
                                                    mygitlab=mygitlab,
                                                    ldap_group=ldap_group,
                                                    create_user=create_user,
                                                    new_group_visibility=new_group_visibility,
                                                    ldap_provider=ldap_provider
                                                    )
        except:
            pass


def sync():
    url = 'https://gitlab.iamchentao.com'
    access = 'glpat-AMZWLMfK2vGimyhzssz3'

    host = "ldap.iamchentao.com"
    admin = 'cn=admin,dc=lab,dc=com'
    passwd = '0chen0TAO0@'
    base_user = 'ou=People,ou=ETH,dc=lab,dc=com'
    base_group = 'ou=ExperimentalQuantumEngineering,ou=PHY,ou=Depart,ou=ETH,dc=lab,dc=com'
    classname = ["groupOfUniqueNames", "posixGroup"]
    # pattern="M*"
    pattern = None

    mygitlab = MyGitlab(url=url, access_token=access, ssl_verify=True)
    mygitlab.connect()

    condition = GroupSearchCon(base=base_group, name_like=pattern, classname=classname)
    user_con = UserSearchCon(base=base_user)
    ldap = LDAP(host=host, admin=admin, password=passwd)
    myldap = myLDAP(ldap=ldap)
    gitlab_gm = mygitlab.get_group_member_all()
    gitlab_g = mygitlab.get_groups_all_names()
    ldap_gm = myldap.get_users(group_Con=condition, user_Con=user_con)


@dataclass
class MyConfig:

    def from_dict(self, value: dict[str, Any]) -> None:
        self_dict = self.__dict__
        for key in self_dict:
            if key in value:
                self_dict[key] = value[key]

    def asdict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))

@dataclass
class LDAP_Config(MyConfig):
    host: str = ""
    admin: str = ''
    password: str = ''
    base_user: str = ''
    base_group: str = ''
    group_class: list[str] = field(default_factory=lambda: ["groupOfUniqueNames", "posixGroup"])
    group_like = '*'

@dataclass
class Gitlab_Config(MyConfig):
    url: str = ''
    access: str = ''
    create_user: bool = False
    new_group_visibility: str = 'private'
    ldap_provider: str = 'ldapmain'


@dataclass
class Sync:
    gitlab: Gitlab_Config = field(default_factory=Gitlab_Config)
    LDAP: Gitlab_Config = field(default_factory=LDAP_Config)

    def read_from_json(self, filename='./config.json') -> None:
        with open(filename) as f:
            config = json.load(f)
        self.gitlab.from_dict(value=config['gitlab'])
        self.gitlab.from_dict(value=config['LDAP'])

    def weite_to_json(self, filename='./config.json') -> None:
        with open(filename, 'w') as f:
            json.dump(asdict(self), f, indent=4)


if __name__ == '__main__':
    a = Sync()
    # print(a)
    a.weite_to_json()
