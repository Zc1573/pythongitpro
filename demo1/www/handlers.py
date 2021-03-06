#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'WangCY'

'''
request handler
'''

from webcore import get,post
from models import User,Blog,Comment,next_id
from apiserr import Page,APIValueError,APIResourceNotFoundError,APIPermissionError
from config import configs
from aiohttp import web
import asyncio,time,hashlib,logging,re,json,markdown2

COOKIE_NAME = 'wangsession'
_COOKIE_KEY = configs['session']['secret']

def checkAdmin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()

def getPageIndex(page_str):
    p = 1
    try:
        p = int(page_str)
    except ValueError as e:
        pass
    if p < 1:
        p = 1
    return p

def textToHtml(text):
    lines = map(lambda s:'<p>%s</p>'% s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),filter(lambda s: s.strip()!='',text.split('\n')))
    return ''.join(lines)

def userToCookie(user,max_age):
    '''
    :param user:
    :param max_age:
    :return:
    '''
    # build cookie string by: id-expires-sha1
    expires = str(int(time.time() + max_age))
    s = '%s-%s-%s-%s'% (user.id,user.passwd,expires,_COOKIE_KEY)
    L = [user.id,expires,hashlib.sha1(s.encode('utf-8')).hexdigest()]
    return '-'.join(L)

async def cookieToUser(cookie_str):
    '''
    :param cookiestr:
    :return:
    '''
    if not cookie_str:
        return None
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        uid,expires,sha1 = L
        if int(expires) < time.time():
            return  None
        user = await User.find(uid)
        if user is None:
            return None
        s = '%s-%s-%s-%s' % (uid, user.passwd, expires, _COOKIE_KEY)
        if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():
            logging.info('invalid sha1')
            return None
        user.passwd = '******'
        return user
    except Exception as e:
        logging.exception(e)
        return None

@get('/')
async def index(*,page='1'):
    pageIndex = getPageIndex(page)
    num  = await Blog.findNumber('count(id)')
    page = Page(num)
    if num == 0:
        blogs = []
    else:
        blogs = await Blog.findAll(orderBy='created_at desc', limit=(page.offset, page.limit))
    return {
        '__template__':'blogs.html',
        'page':page,
        'blogs':blogs
    }

@get('/register')
def register():
    return {
        '__template__': 'register.html'
    }

@get('/signin')
def signin():
    return {
        '__template__': 'signin.html'
    }

@get('/signout')
def signout(request):
    referer = request.headers.get('Referer')
    r = web.HTTPFound(referer or '/')
    r.set_cookie(COOKIE_NAME,'-deleted-',max_age=0,httponly=True)
    logging.info('user signed out.')
    return r

_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1 = re.compile(r'^[0-9a-f]{40}$')

@post('/api/users')
async def register_user(*,email,name,passwd):
    if not name or not name.strip():
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    if not passwd or not _RE_SHA1.match(passwd):
        raise APIValueError('passwd')
    user = await User.findAll('email=?',[email])
    if len(user) > 0:
        raise APIValueError('register:failed', 'email', 'Email is already in use.')
    uid = next_id()
    sha1_passwd = '%s:%s'% (uid,passwd)
    user = User(id=uid, name=name.strip(), email=email, passwd=hashlib.sha1(sha1_passwd.encode('utf-8')).hexdigest(),
                image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
    await user.save()
    # make session cookie:
    r = web.Response()
    r.set_cookie(COOKIE_NAME,userToCookie(user,86400),max_age=86400,httponly=True)
    user.passwd = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user,ensure_ascii=False).encode('utf-8')
    return r

@post('/api/authLogin')
async def authLogin(*,email,passwd):
    if not email:
        raise APIValueError('email','Invalid email')
    if not passwd:
        raise APIValueError('passwd','Invalid passwd')
    users = await User.findAll('email=?',[email])
    if len(users) == 0:
        raise APIValueError('email', 'Email not exist')
    user = users[0]
    # check passwd:
    sha1 = hashlib.sha1()
    sha1.update(user.id.encode('utf-8'))
    sha1.update(b':')
    sha1.update(passwd.encode('utf-8'))
    if user.passwd != sha1.hexdigest():
        raise APIValueError('passwd', 'Invalid password')
    # authenticate ok, set cookie:
    r = web.Response()
    r.set_cookie(COOKIE_NAME,userToCookie(user,86400),max_age=86400,httponly=True)
    user.passwd = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user,ensure_ascii=False).encode('utf-8')
    return r

@get('/blog/{id}')
async def getBlog(id):
    blog = await Blog.find(id)
    comments = await Comment.findAll('blog_id=?',[id],orderBy='created_at desc')
    for c in comments:
        c.html_content = textToHtml(c.content)
    blog.html_content = markdown2.markdown(blog.content)
    return {
        '__template__': 'blog.html',
        'blog': blog,
        'comments': comments
    }

@get('/manage/')
def manage():
    return 'redirect:/manage/comments'

@get('/manage/comments')
def manageComments(*,page='1'):
    return {
        '__template__': 'manage_comments.html',
        'page_index': getPageIndex(page)
    }

@get('/manage/blogs/create')
def manageCreateBlog():
    return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs'
    }

@get('/manage/blogs/edit')
def manageEditBlog(*,id):
    return {
        '__template__': 'manage_blog_edit.html',
        'id': id,
        'action': '/api/blogs/%s'% id
    }

@get('/manage/blogs')
def manageBlogs(*,page='1'):
    return {
        '__template__': 'manage_blogs.html',
        'page_index': getPageIndex(page)
    }

@get('/manage/users')
def manageUsers(*,page='1'):
    return {
        '__template__': 'manage_users.html',
        'page_index': getPageIndex(page)
    }

@get('/api/comments')
async def apiComments(*,page='1'):
    pageIndex = getPageIndex(page)
    num = await Comment.findNumber('count(id)')
    p = Page(num,pageIndex)
    if num ==0:
        return dict(page=p,comments=())
    comments = await Comment.findAll(orderBy='created_at desc',limit=(p.offset,p.limit))
    return dict(page=p,comments=comments)

@post('/api/blogs/{id}/comments')
async def apiCreateComment(id,request,*,content):
    user = request.__user__
    if user is None:
        raise APIPermissionError('Please signin first')
    if not content or not content.strip():
        raise APIValueError('content')
    blog = await Blog.find(id)
    if blog is None:
        raise APIResourceNotFoundError('blog')
    comment = Comment(blog_id=blog.id,user_id=user.id,user_name=user.name,user_image=user.image,content=content.strip())
    await comment.save()
    return comment

@post('/api/comments/{id}/delete')
async def apiDeleteComments(id,request):
    checkAdmin(request)
    c = await Comment.find(id)
    if c is None:
        raise APIResourceNotFoundError('Comment')
    await c.remove()
    return dict(id=id)

@get('/api/users')
async def apiGetUsers(*,page='1'):
    pageIndex = getPageIndex(page)
    num = await User.findNumber('count(id)')
    p = Page(num,pageIndex)
    if num == 0:
        return dict(page=p,users=())
    users = await User.findAll(orderBy='created_at desc',limit=(p.offset,p.limit))
    for u in users:
        u.passwd = '******'
    return dict(page=p,users=users)

@get('/api/blogs')
async def apiBlogs(*,page='1'):
    page_index = getPageIndex(page)
    num = await Blog.findNumber('count(id)')
    p = Page(num,page_index)
    if num == 0:
        return dict(page=p,blogs=())
    blogs = await Blog.findAll(orderBy='created_at desc',limit=(p.offset,p.limit))
    return dict(page=p,blogs=blogs)

@post('/api/blogs')
async def createBlog(request,*,name,summary,content):
    checkAdmin(request)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog = Blog(user_id=request.__user__id,user_name=request.__user__.name,user_image=request.__user__.image,name=name.strip(),summary=summary.strip(),content=content.strip())
    await blog.save()
    return blog

@get('/api/blogs/{id}')
async def apiGetBlog(*,id):
    blog = await Blog.find(id)
    return blog

@post('/api/blogs/{id}')
async def apiUpdateBlog(id,request,*,name,summary,content):
    checkAdmin(request)
    blog = await Blog.find(id)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog.name = name.strip()
    blog.summary = summary.strip()
    blog.content = summary.strip()
    await blog.update()
    return blog

@post('/api/blogs/{id}/delete')
async def apiDeleteBlog(request,*,id):
    checkAdmin(request)
    blog = await Blog.find(id)
    await blog.remove()
    return dict(id=id)