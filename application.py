import pandas as pd
import openpyxl
import urllib.request
import json
from pandas import DataFrame 
from flask import Flask, request, redirect, g, render_template, session
from spotify_requests import spotify
from azureml_requests import playlistazureml, recommendazureml

app = Flask(__name__)
app.secret_key = 'some key for session'

# ----------------------- AUTH API PROCEDURE -------------------------

@app.route("/auth")
def auth():
    return redirect(spotify.AUTH_URL)


@app.route("/callback/")
def callback():

    auth_token = request.args['code']
    auth_header = spotify.authorize(auth_token)
    session['auth_header'] = auth_header

    return profile()

def valid_token(resp):
    return resp is not None and not 'error' in resp
# -------------------------- API REQUESTS ----------------------------


@app.route("/")
def index():
    return render_template('index.html')


@app.route('/search/')
def search():
    try:
        search_type = request.args['search_type']
        name = request.args['name']
        return make_search(search_type, name)
    except:
        return render_template('search.html')


@app.route('/search/<search_type>/<name>')
def search_item(search_type, name):
    return make_search(search_type, name)


def make_search(search_type, name):
    if search_type not in ['artist', 'album', 'playlist', 'track']:
        return render_template('index.html')

    data = spotify.search(search_type, name)
    api_url = data[search_type + 's']['href']
    items = data[search_type + 's']['items']

    return render_template('search.html',
                           name=name,
                           results=items,
                           api_url=api_url,
                           search_type=search_type)


@app.route('/artist/<id>')
def artist(id):
    artist = spotify.get_artist(id)

    if artist['images']:
        image_url = artist['images'][0]['url']
    else:
        image_url = 'http://bit.ly/2nXRRfX'

    tracksdata = spotify.get_artist_top_tracks(id)
    tracks = tracksdata['tracks']

    related = spotify.get_related_artists(id)
    related = related['artists']

    return render_template('artist.html',
                           artist=artist,
                           related_artists=related,
                           image_url=image_url,
                           tracks=tracks)


@app.route('/profile')
def profile():
    if 'auth_header' in session:
        auth_header = session['auth_header']
        # get profile data
        profile_data = spotify.get_users_profile(auth_header)

        # get user playlist data
        playlist_data = spotify.get_users_playlists(auth_header)

        # get user recently played tracks
        recently_played = spotify.get_users_recently_played(auth_header)
        
        # get user top artist
        top_artists_data = spotify.get_users_top_artists(auth_header)
        
        # get user top tracks
        top_tracks_data = spotify.get_users_top_tracks(auth_header)
        
        if valid_token(recently_played):
            return render_template("profile.html",
                               user=profile_data,
                               playlists=playlist_data["items"],
                               recently_played=recently_played["items"],
                               top_artists=top_artists_data["items"],
                               top_tracks=top_tracks_data["items"])

    return render_template('profile.html')


@app.route('/featured_playlists')
def featured_playlists():
    if 'auth_header' in session:
        auth_header = session['auth_header']
        hot = spotify.get_featured_playlists(auth_header)
        if valid_token(hot):
            return render_template('featured_playlists.html', hot=hot)

    return render_template('profile.html')

@app.route('/track_list')
def track_list():
    track_list = spotify.get_several_tracks
    tracks = track_list ['tracks']
    return render_template ('track_list.html', track_list=track_list, tracks=tracks)

@app.route('/playlist')
def playlist():
    if 'auth_header' in session:
        auth_header = session['auth_header']
        offset = 0
        songs = []
        items = []
        ids = []
        track_info = []
        playlist_id = request.args['id']
        # get playlist
        while True:
            content = spotify.get_playlist_tracks(auth_header, playlist_id)
            songs += content['items']
            if content['next'] is not None:
                offset += 100
            else:
                break
        #flatten playlist tracks and artist info
        genre_info = []
        list_of_ids = []
        for t in songs:
            ids.append(t['track']['id'])
            artist_id = t['track']['artists'][0]['id']
            artist_name = t['track']['artists'][0]['name']
            track_info.append([
                    t['track']['id'],
                    t['track']['name'],
                    t['track']['popularity'],
                    artist_id,
                    artist_name
                    ])
        for ta in songs:
            for a in ta['track']['artists']:
                list_of_ids.append(a['id'])
        print (track_info)
        #get artist genre
        artist_json = spotify.get_several_artists(auth_header, list_of_ids)
        for g in artist_json['artists']:
            genre_info.append([
                g['id'],
                g['genres'][0]
                ])
        genredf = pd.DataFrame(genre_info, columns = 
                               [
                                'artist_id',
                                'genre'
                               ]
                               )
        trackdf = pd.DataFrame(track_info, columns=
                          [
                          'id',
                          'name',
                          'popularity',
                          'artist_id',
                          'artist_name'
                          ]
                           )
        # get playlist track features
        index = 0
        global playlist_audio_features

        while index < len(ids):
            playlist_audio_features = spotify.get_audio_feature(auth_header,ids[index:index + 50])
            index += 50
        # build playlist trackfeatures
        features_list = []
        for features in playlist_audio_features['audio_features']:
            features_list.append([
                features['id'],
                features['acousticness'],features['danceability'],
                features['energy'],features['liveness'],
                features['speechiness'],features['valence']
                ])

        featuredf = pd.DataFrame(features_list, columns=
                          [
                          'id',
                          'acousticness', 'danceability',
                          'energy', 'liveness',
                          'speechiness', 'valence'
                          ]
                           )
        #merge track featrues and genre
        trackmerge = pd.merge(trackdf, featuredf, on='id')
        playlistinput = pd.merge(trackmerge, genredf, on='artist_id')
        #pust to ML input and web
        playlistinput.to_csv('playlistinput.csv', sep = ',', index = False)
        return render_template('playlist.html',
                               playlist_id=playlist_id,
                               content=content,
                               playlistinput=playlistinput.to_html())


@app.route('/playlistresult')
def playlistresult():
    mlbatchrequest = playlistazureml.invokeBatchExecutionService()
    playlistoutput = pd.read_csv('playlistoutput.csv', encoding = "ISO-8859-1")
    playlistoutput.loc['avg'] = playlistoutput.mean()
    return render_template("playlistresult.html", playlistoutput=playlistoutput.to_html())

@app.route('/recommend')
def recommend():
    if 'auth_header' in session:
        auth_header = session['auth_header']
        playlistoutput = pd.read_csv('playlistoutput.csv', encoding = "ISO-8859-1")
        #build recommendation params ((TO DO: seed on top 5 genres, min/max of features closest to center) CURENT seed track is top 5 track ids, avg of features for target)
        seedids = playlistoutput.loc[0,'id']
        playlistoutput.loc['avg'] = playlistoutput.mean()
        popavg = playlistoutput.loc['avg','popularity']
        targetpop = int(round(popavg))
        targetdance = playlistoutput.loc['avg','danceability']
        targetenergy = playlistoutput.loc['avg','energy']
        #get spotify recommednations (TO DO dynamically build params)
        query_parameters = {
            "seed_tracks": seedids,
            "limit": 100,
            "market": "US",
            "target_popularity": targetpop,
            "target_danceability": targetdance,
            "target_energy": targetenergy
            }
        recommendtracks = spotify.get_recommendations(auth_header,query_parameters)
        ids = []
        track_info = []
        for i in recommendtracks['tracks']:
            id = i['id']
            ids.append(i['id'])
            track_info.append([
                i['id'],
                i['name'],
                i['popularity']
                ])
        trackdf = pd.DataFrame(track_info, columns=
                          [
                          'id',
                          'name',
                          'popularity'
                          ]
                           )
        recommendfeatures = spotify.get_audio_feature(auth_header, ids)
        # build recommnedation features
        features_list = []
        for features in recommendfeatures['audio_features']:
            features_list.append([
                features['id'],
                features['acousticness'],features['danceability'],
                features['energy'],features['liveness'],
                features['speechiness'],features['valence']
                ])

        featuredf = pd.DataFrame(features_list, columns=
                          [
                          'id',
                          'acousticness', 'danceability',
                          'energy', 'liveness',
                          'speechiness', 'valence'
                          ]
                           )
        recommendinput = pd.merge(trackdf, featuredf, on='id')
        #inputfile for recommendation ML request
        recommendinput.to_csv('recommendinput.csv', sep = ',', index = False)
        return render_template("recommend.html",
                            recommendtracks=recommendtracks["tracks"],
                            recommendfeatures=recommendfeatures,
                            recommendinput=recommendinput.to_html()
                            )

@app.route('/stagedplaylist')
def stagedplaylist():
    if 'auth_header' in session:
        auth_header = session['auth_header']
        songarray = {"uris":[]}
        mlbatchrequest = recommendazureml.invokeBatchExecutionService()
        #get top10 rows from output (TO DO: selected top 25 based on distant to cluster)
        recommendoutput = pd.read_csv('recommendoutput.csv', encoding = "ISO-8859-1", nrows=10)
        #build input for webplayback
        ids = recommendoutput['id'].values
        songlist = ["spotify:track:" + s for s in ids]
        songjson = json.dumps( {'uris':(songlist)})
        #get track info
        stagedtracks = spotify.get_several_tracks(auth_header, ids)
        return render_template("stagedplaylist.html",
                            songjson=songjson,
                            stagedtracks=stagedtracks['tracks']
                            )

if __name__ == "__main__":
    
    app.run(debug=True, port=spotify.PORT)

