import urllib.parse
import base64
import idna
import time
import sys
import re
import os

from bs4 import BeautifulSoup
import requests

from .downloader import *


REDECANAIS_URL = 'https://redecanais.ec'
VIDEO_HOST_URL = 'https://xn----------------g34l3fkp7msh1cj3acobj33ac2a7a8lufomma7cf2b1sh.xn---1l1--5o4dxb.xn---22--11--33--99--75---------b25zjf3lta6mwf6a47dza94e.xn--pck.xn--zck.xn--0ck.xn--pck.xn--yck.xn-----0b4asja8cbew2b4b0gd0edbjm2jpa1b1e9zva7a0347s4da2797e7qri.xn--1ck2e1b/player3'

def convert_to_punycode(url):
    # Decode the URL from percent encoding
    decoded_url = urllib.parse.unquote(url)
    
    # Parse the URL to extract the domain
    parsed_url = urllib.parse.urlparse(decoded_url)
    
    # Convert the domain to Punycode
    punycode_domain = idna.encode(parsed_url.netloc).decode('utf-8')
    
    # Rebuild the URL with the Punycode domain
    punycode_url = urllib.parse.urlunparse((
        parsed_url.scheme,           # Scheme (http, https)
        punycode_domain,             # Punycode domain
        parsed_url.path,             # Path
        parsed_url.params,           # Params
        parsed_url.query,            # Query
        parsed_url.fragment          # Fragment
    ))
    
    return punycode_url


def decode_redecanais(payload: list[str], key: int):
    final_chars = []
    for b64_str in payload:
        try:
            # decode the base 64 string back to utf8
            decoded_str = base64.b64decode(b64_str).decode()

            # extract the integer representing the character
            encoded_char = int(re.sub(r'\D', '', decoded_str))

            # subtract the key to get the unicode value for the character
            encoded_char -= key

            # append charcter to final string
            final_chars.append(chr(encoded_char))

        except:
            continue
    
    # return the decoded content
    return ''.join(final_chars).encode('latin1').decode('utf8')


def decode_from_response(response: requests.Response):
    # iterate through the response and extract all the encoded strings
    prev_chunk = ''
    b64_list = []
    for chunk in response.iter_content(1024):
        # extract b64 strings from current chunk plus what was left from the previous chunk
        curr_chunk = prev_chunk + chunk.decode()
        b64_strs = re.findall(r'((?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=))', curr_chunk)

        # remove all the b64 strings from the current chunk and save it as previous chunk
        # also remove empty strings and whitespaces
        prev_chunk = re.sub(r'(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)', '', curr_chunk)
        prev_chunk = re.sub(r'( |\n)*"",', '', prev_chunk)

        # save all b64 strings to the list
        [b64_list.append(s) for s in b64_strs]

    # extract key from what was left from prev_chunk
    key = re.findall(r'.replace.* *?- *?(\d+)\)', prev_chunk)
    if key:
        key = int(key[0])
    
    return decode_redecanais(b64_list, key)


def get_download_page_url(video_url: str):
    redirect = requests.get(
        video_url,
        allow_redirects=False
        )

    # idna encode url to work with requests
    encoded_url = redirect.headers["location"]
    try:
        idna_url = convert_to_punycode(f'https:{encoded_url}')
    except:
        idna_url = encoded_url

    # parse the decoded html to extract serverforms url and token from the decoded html
    response = requests.get(idna_url)
    decoded_html = BeautifulSoup(decode_from_response(response), 'html.parser')
    scripts = decoded_html.find_all('script')
    for script in scripts:
        url_match = re.findall(r'url: \'\.(/.+?)\'', script.text)
        if url_match:
            url_match = url_match[0]
            serverforms_url = f'{VIDEO_HOST_URL}{url_match}'
            rctoken = re.findall(r'\'rctoken\':\'(.+?)\'', script.text)[0]
    
    # request the serverforms url
    serverforms_response = requests.post(
        serverforms_url, 
        data={'rctoken': rctoken}
        )
    
    # get download page url from serverforms
    download_page_url = re.findall(r'baixar=\"https://.+?r=(.+?)\"', serverforms_response.text)
    if download_page_url:
        return download_page_url[0]
    else:
        msg = 'Could not extract download page url from serverforms html.'
        raise Exception(msg)


def get_download_link(download_page_url: str):
    # decode download page
    download_page_response = requests.get(download_page_url)
    download_page = decode_from_response(download_page_response)

    # extract download link from download page
    download_link = re.findall(r'const *redirectUrl *= *\'(.+?)\'', download_page)
    if download_link:
        return f'https:{download_link[0]}'
    else:
        msg = 'Could not extract download link from download page'
        raise Exception(msg)


def get_series_info(series_page_url: str):
    # get html from request
    response = requests.get(series_page_url)
    html = BeautifulSoup(response.text, 'html.parser')

    # get page title
    title = html.title.text

    # get div containing the episodes
    episodes_div = html.find('div', class_='pm-category-description')
    if episodes_div is None:
        episodes_div = html.find('div', {'itemprop': 'description'})

    # get the links of every episode and their information
    links: list[BeautifulSoup] = episodes_div.find_all('a')
    link_info_list = []
    for link in links:
        link_info = {
            'url': link.get('href'),
            'url_text': link.text,
            'number_str': link.previous_sibling.previous_sibling,
            'title_str': link.previous_sibling,
        }
        link_info_list.append(link_info)

    series_dict = {'title': title, 'seasons': []}
    season_dict = {'season': 0, 'episodes': []}
    others_dict = {'others': []}
    last_episode_number = 999
    season_number = 0
    for i, link in enumerate(link_info_list):
        if link is None:
            continue

        # get episode title
        episode_title = link['title_str'].text.strip(' -')

        # get episode number
        episode_number = re.sub(r"\D", '', link['number_str'].text)
        if episode_number:
            episode_number = int(episode_number)
        else:
            episode_title = link['number_str'].text + episode_title
            episode_number = last_episode_number

        # get new season if episode number went back to one
        if last_episode_number > episode_number:
            season_number += 1
            
            # save last season dict
            if season_dict['episodes']:
                series_dict['seasons'].append(season_dict)
            
            # create new season dict
            season_dict = {'season': season_number, 'episodes': []}
        
        # save to others if no episode number was found
        elif last_episode_number == episode_number:
            others_dict['others'].append({'title': episode_title, 'url_1': f'{REDECANAIS_URL}{link['url']}'})
            continue
        
        # create episode dict
        episode_dict = {
            'number': episode_number,
            'title': episode_title,
            'url_1': f'{REDECANAIS_URL}{link['url']}',
            'url_2': '',
        }

        # include subtitled url as url_2, if avaliable
        if link['url_text'] == 'Dublado':
            next_link = link_info_list[i+1]
            if next_link['url_text'] == 'Legendado':
                episode_dict.update({'url_2': f'{REDECANAIS_URL}{next_link['url']}'})
                link_info_list[i+1] = None

        # update season dict and update last_episode
        season_dict['episodes'].append(episode_dict)
        last_episode_number = episode_number

    # append the final season to the series dict
    series_dict['seasons'].append(season_dict)

    # append others section if not epmpty
    if others_dict['others']:
        series_dict.update(others_dict)
    
    return series_dict

# source can be the title of the page or an url
def get_video_info(source: str):
    if 'https://' in source:
        # get video page
        video_page_response = requests.get(source)
        decoded_video_page = decode_from_response(video_page_response)
        video_page_html = BeautifulSoup(decoded_video_page, 'html.parser')

        # get page title
        title = video_page_html.find('title').text
    
    else:
        title = source

    # get video info
    title_info = title.split(' - ')
    if 'Episódio' in ''.join(title_info[1:]):
        # extract information from video title
        serie_name = re.sub(r'[\\\/\:\"\*\?\<\>\|]', '', title_info[0].strip())

        season = 0
        episode = 0
        title = ''
        ep_found = False
        for info in title_info[1:]:
            if ep_found:
                title = re.sub(r'[\\\/\:\"\*\?\<\>\|]', '', info.strip())
            elif 'Temporada' in info:
                season = int(re.sub(r'\D', '', info))
            elif 'Episódio' in info:
                episode = int(re.sub(r'\D', '', info))
                ep_found = True
        
        # arrange information on a dict
        return {'type': 'serie', 'serie_name': serie_name, 'season': season, 'episode': episode, 'title': title}
    
    else:
        # extract information from video title
        title = re.sub(r'[\\\/\:\"\*\?\<\>\|]', '', title_info[0].strip())
        
        # arrange information on a dict
        return {'type': 'movie', 'title': title}


# TODO: update it to receive url and output file
# TODO: create function to manage downloads
def download(video_page_url: str):
    # get video page
    video_page_response = requests.get(video_page_url)
    decoded_video_page = decode_from_response(video_page_response)
    video_page_html = BeautifulSoup(decoded_video_page, "html.parser")

    # get video info
    title = video_page_html.find('title').text
    video_info = get_video_info(title)

    # get video url
    for iframe in video_page_html.find_all('iframe'):
        name = iframe.get('name')
        if name is not None and name == 'Player':
            video_url = iframe.get('src')
            video_url = f'{REDECANAIS_URL}{video_url}'
    
    # get download link
    download_page_url = get_download_page_url(video_url)
    download_link = get_download_link(download_page_url)

    # define a name for the output file
    if video_info['type'] == 'movie':
        file_dir = './'
        file_name = f'{video_info['title']}.mp4'
    else:
        file_dir = f'{video_info['serie_name']}/{video_info['season']}/'
        file_name = f"{video_info['episode']}{f' - {video_info['title']}' if video_info['title'] else ''}.mp4"

    # create output dir
    os.makedirs(file_dir, exist_ok=True)
    file_path = f'{file_dir}{file_name}'

    # start download
    download = Download(
        download_link, 
        file_path,
        headers={'Referer': download_page_url}
        )
    download.start()

    # show progress
    while download.is_running:
        print(f'{file_dir}{file_name} - {download.progress:.2f}%     ', end='\r')
        time.sleep(0.1)
    print(f'{file_dir}{file_name} - 100.00%     ')


def main():
    if len(sys.argv) > 1:
        video_page_url = sys.argv[1]
        if len(sys.argv) > 2:
            start_from = int(sys.argv[2])
        else:
            start_from = 0
    else:
        exit('Example usage: python redecanais.py <video_page_url>')

    download(video_page_url)

if __name__ == "__main__":
    main()