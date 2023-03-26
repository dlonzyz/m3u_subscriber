import concurrent.futures
import math
import socket
import threading
import time
import dnslib

import redis

r = redis.Redis(host='localhost', port=6379)
# 白名单总命中缓存规则，数据中等，是实际命中的规则缓存
white_list_tmp_policy = {}
# 白名单总命中缓存，数据最少，是实际访问的域名缓存
white_list_tmp_cache = {}
# 未知域名访问缓存记录
unkown_list_tmp_cache = {}
# 下载的域名白名单存储到redis服务器里
REDIS_KEY_WHITE_DOMAINS = "whitedomains"
# 下载的域名黑名单存储到redis服务器里
REDIS_KEY_BLACK_DOMAINS = "blackdomains"
# 黑名单总命中缓存规则，数据中等，是实际命中的规则缓存
black_list_tmp_policy = {}
# 黑名单总命中缓存，数据最少，是实际访问的域名缓存
black_list_tmp_cache = {}
white_list_nameserver_policy = {}
black_list_policy = {}


# 规则：先查unkown_list_tmp_cache，有的话转发5335,
# 没有再查black_list_tmp_cache，有记录直接转发5335,
# 没有再查white_list_tmp_cache,有记录直接转发5336，
# 没有再查black_list_tmp_policy,命中则更新black_list_tmp_cache，转发5335。
# 没有则查white_list_tmp_policy,命中则更新white_list_tmp_cache，转发5336。
# 没有命中则black_list_policy，查到则更新black_list_tmp_policy，blacl_list_tmp_cache，再转发5335
# 没有命中则white_list_nameserver_policy，查到则更新white_list_tmp_policy，white_list_tmp_cache，再转发5336
# 没有命中则更新unkown_list_tmp_cache，转发给127.0.0.1#5335


# 检测域名是否在记录的黑名单域名策略缓存  是-true  不是-false
def inBlackListPolicyCache(domain_name_str):
    # 在今日已经命中的规则里查找
    for vistedDomain in black_list_tmp_policy.keys():
        # 新域名在规则里有类似域名，更新black_list_tmp_cache
        if vistedDomain in domain_name_str:
            black_list_tmp_cache[domain_name_str] = ""
            return True
        # 缓存域名在新域名里有匹配
        if domain_name_str in vistedDomain:
            black_list_tmp_cache[domain_name_str] = ""
            return True
    return False


# 检测域名是否在记录的黑名单域名缓存  是-true  不是-false
def inBlackListCache(domain_name_str):
    for recordThiteDomain in black_list_tmp_cache.keys():
        # 新域名在缓存里有类似域名
        if recordThiteDomain in domain_name_str:
            return True
        # # 缓存域名在新域名里有匹配
        if domain_name_str in recordThiteDomain:
            return True
    return False


# 检测域名是否在未知缓存里，是-True,不是-False
def inUnkownCache(domain_name_str):
    # 命中未知域名缓存，直接丢给5335
    for unkown in unkown_list_tmp_cache.keys():
        # 新域名在缓存里有类似域名
        if unkown in domain_name_str:
            return True
        # 缓存域名在新域名里有匹配
        if domain_name_str in unkown:
            return True
    return False


# 检测域名是否在记录的白名单域名缓存  是-true  不是-false
def inWhiteListCache(domain_name_str):
    for recordThiteDomain in white_list_tmp_cache.keys():
        # 新域名在缓存里有类似域名
        if recordThiteDomain in domain_name_str:
            return True
        # # 缓存域名在新域名里有匹配
        if domain_name_str in recordThiteDomain:
            return True
    return False


# 检测域名是否在记录的白名单域名策略缓存  是-true  不是-false
def inWhiteListPolicyCache(domain_name_str):
    # 在今日已经命中的规则里查找
    for vistedDomain in white_list_tmp_policy.keys():
        # 新域名在规则里有类似域名，更新white_list_tmp_cache
        if vistedDomain in domain_name_str:
            white_list_tmp_cache[domain_name_str] = ""
            return True
        # 缓存域名在新域名里有匹配
        if domain_name_str in vistedDomain:
            white_list_tmp_cache[domain_name_str] = ""
            return True
    return False


# 检测域名是否在全部黑名单域名策略  是-true  不是-false
def inBlackListPolicy(domain_name_str):
    if len(black_list_policy) == 0:
        initBlackList()
    if black_list_policy:
        jump = 0
        count = 0
        fail = 0
        maxThread = 100
        items = sorted(black_list_policy.keys())
        length = len(items)
        # 计算每个线程处理的数据大小
        chunk_size = math.ceil(length / maxThread)
        with concurrent.futures.ThreadPoolExecutor(max_workers=maxThread) as executor:
            futures = []
            for i in range(maxThread):
                start_index = i * chunk_size
                end_index = min(start_index + chunk_size, length)
                black_list_chunk = items[start_index:end_index]
                future = executor.submit(check_domain_inBlackListPolicy, domain_name_str, black_list_chunk)
                futures.append(future)
                if future.result():
                    jump += 1
                    break
                else:
                    fail += 1
            if count == 0:
                if jump > 0:
                    count += 1
                    return True
                elif fail == 9:
                    count += 1
                    return False
    else:
        return False


def check_domain_inBlackListPolicy(domain_name_str, black_list_chunk):
    for key in black_list_chunk:
        # 新域名在全部规则里有类似域名，更新缓存与策略缓存
        if key in domain_name_str:
            black_list_tmp_cache[domain_name_str] = ""
            black_list_tmp_policy[key] = ""
            return True
        # 缓存域名在新域名里有匹配
        if domain_name_str in key:
            black_list_tmp_cache[domain_name_str] = ""
            black_list_tmp_policy[key] = ""
            return True


# 检测域名是否在全部白名单域名策略  是-true  不是-false
def inWhiteListPolicy(domain_name_str):
    if len(white_list_nameserver_policy) == 0:
        initWhiteList()
    if white_list_nameserver_policy:
        jump = 0
        count = 0
        fail = 0
        maxThread = 100
        items = sorted(white_list_nameserver_policy.keys())
        length = len(items)
        # 计算每个线程处理的数据大小
        chunk_size = math.ceil(length / maxThread)
        with concurrent.futures.ThreadPoolExecutor(max_workers=maxThread) as executor:
            futures = []
            for i in range(0, maxThread):
                start_index = i * chunk_size
                end_index = min(start_index + chunk_size, length)
                white_list_chunk = items[start_index:end_index]
                future = executor.submit(check_domain_inWhiteListPolicy, domain_name_str, white_list_chunk)
                futures.append(future)
                if future.result():
                    jump += 1
                    break
                else:
                    fail += 1
                if count == 0:
                    if jump > 0:
                        count += 1
                        return True
                    elif fail == 9:
                        count += 1
                        return False
    else:
        return False


def check_domain_inWhiteListPolicy(domain_name_str, white_list_chunk):
    for key in white_list_chunk:
        # 新域名在全部规则里有类似域名，更新whiteDomainPolicy
        if domain_name_str in key:
            white_list_tmp_cache[domain_name_str] = ""
            white_list_tmp_policy[key] = ""
            return True
        # 缓存域名在新域名里有匹配
        if key in domain_name_str:
            white_list_tmp_cache[domain_name_str] = ""
            white_list_tmp_policy[key] = ""
            return True
    return False


# 是中国域名   是-true  不是-false
def isChinaDomain(data):
    dns_msg = dnslib.DNSRecord.parse(data)
    domain_name = dns_msg.q.qname
    domain_name_str = str(domain_name)
    domain_name_str = domain_name_str[:-1]
    # 在已经命中的外国域名查找，直接丢给5335
    if inBlackListCache(domain_name_str):
        return False
    # 在今日已经命中的黑名单规则里查找
    if inBlackListPolicyCache(domain_name_str):
        return False
    # 黑名单规则里查找
    if inBlackListPolicy(domain_name_str):
        return False
    # 在已经命中的中国域名查找，直接丢给5336
    if inWhiteListCache(domain_name_str):
        return True
    # 在今日已经命中的白名单规则里查找
    if inWhiteListPolicyCache(domain_name_str):
        return True
    # 在全部白名单规则里查找
    if inWhiteListPolicy(domain_name_str):
        return True
    # # 命中未知域名缓存，直接丢给5335
    # if inUnkownCache(domain_name_str):
    #     return False
    # unkown_list_tmp_cache[domain_name_str] = ""
    return False


def simpleDomain(domain_name):
    if domain_name.encode().startswith(b"www."):
        simple_domain_name = domain_name.substring(4)
    else:
        simple_domain_name = domain_name
    return simple_domain_name


def redis_get_map(key):
    redis_dict = r.hgetall(key)
    python_dict = {key.decode('utf-8'): value.decode('utf-8') for key, value in redis_dict.items()}
    return python_dict


# 定义一个函数，用于接收客户端的DNS请求


def dns_query(data):
    # 解析客户端的DNS请求
    # domain_name = data[2:-5].decode('utf-8')
    # simple_domain_name = simpleDomain(domain_name)
    if isChinaDomain(data):
        port = 5336
    else:
        port = 5335
    # 随机选择一个DNS服务器openwrt
    # dns_server = '127.0.0.1'
    # 电脑测试，实际上openwrt也只能使用这个，也就是软路由lan口，127.0.0.1完全没有用，妈的
    dns_server = '192.168.5.1'
    # 向DNS服务器发送请求
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(data, (dns_server, port))
    # 接收DNS服务器的响应
    response, addr = sock.recvfrom(4096)
    sock.close()
    # 返回响应给客户端
    return response


def initWhiteList():
    whitelist = redis_get_map(REDIS_KEY_WHITE_DOMAINS)
    if whitelist and len(whitelist) > 0:
        white_list_nameserver_policy.update(whitelist)


def initBlackList():
    blacklist = redis_get_map(REDIS_KEY_BLACK_DOMAINS)
    if blacklist and len(blacklist) > 0:
        black_list_policy.update(blacklist)


# redis增加和修改
def redis_add(key, value):
    r.set(key, value)


# redis查询
def redis_get(key):
    return r.get(key)


# 0-数据未更新 1-数据已更新 max-所有服务器都更新完毕(有max个服务器做负载均衡)
REDIS_KEY_UPDATE_WHITE_LIST_FLAG = "updatewhitelistflag"
REDIS_KEY_UPDATE_BLACK_LIST_FLAG = "updateblacklistflag"


# true-拉取更新吧
def needUpdate(redis_key):
    flag = redis_get(redis_key)
    if flag:
        # 数据没有更新
        if flag == 0:
            return False
        # 服务器全部更新完毕(逻辑不严谨感觉)
        if flag >= 2:
            redis_add(redis_key, 0)
            return False
        # 服务器未全部完成更新(逻辑不严谨，一个服务器的话还能用用)
        else:
            redis_add(redis_key, flag + 1)
            return True
    return False


def init(sleepSecond):
    while True:
        if needUpdate(REDIS_KEY_UPDATE_WHITE_LIST_FLAG):
            initWhiteList()
        if needUpdate(REDIS_KEY_UPDATE_BLACK_LIST_FLAG):
            initBlackList()
        time.sleep(sleepSecond)


# 考虑过线程池或者负载均衡，线程池需要多个端口不大合适，负载均衡似乎不错，但有点复杂，后期看看
if __name__ == '__main__':
    timer_thread1 = threading.Thread(target=init, args=(10,))
    timer_thread1.start()
    # 创建一个UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 绑定本地的IP和端口
        # sock.bind(('', 5911))
        # 电脑监听测试,127.0.0.1是容器内部网络环境
        sock.bind(('127.0.0.1', 53))
        # openwrt监听
        #sock.bind(('0.0.0.0', 5911))
        # 开始接收客户端的DNS请求
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                response = dns_query(data)
                sock.sendto(response, addr)
            except:
                pass
    except:
        pass
    finally:
        sock.close()
        timer_thread1.join()
