# -*- coding: utf-8 -*-
"""
Created on Wed Feb  3 16:48:30 2021

@author: Charlie
"""

from googleapiclient.discovery import build
from google.oauth2 import service_account
import pandas as pd
import numpy as np
import datetime
import time

SERVICE_ACCOUNT_FILE = 'tradetracker-key.json'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

creds = None
creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# The ID spreadsheet.
SAMPLE_SPREADSHEET_ID = '1inoTadIL-m1KNmQMGR4a7ndEUzjWaiq9pF5V_4pfgRQ'


service = build('sheets', 'v4', credentials=creds)

# Call the Sheets API
sheet = service.spreadsheets()
result = sheet.values().get(spreadsheetId=SAMPLE_SPREADSHEET_ID,
                            range='SPY TRADE TRACKER!!A1:H150').execute()
values = result.get('values', [])

def make_df(v):
    df = pd.DataFrame(v)
    df.columns = df.iloc[0].values
    df = df[1:]
    df = df[~df['ENTRY DATE'].isin([np.nan, '', None])]
    df.replace('', np.nan, inplace=True)
    df['ENTRY DATE'] = pd.to_datetime(df['ENTRY DATE'].values, format = '%d/%m/%Y')
    df['EXIT DATE'] = pd.to_datetime(df['EXIT DATE'].values, format = '%d/%m/%Y')
    df['OPEN PRICE'] = df['OPEN PRICE'].astype(float) 
    df['CLOSE PRICE'] = df['CLOSE PRICE'].astype(float)
    df = df[(df['ENTRY DATE']> "2020-12-30 00:00:00")]
    df['SHARES'] = df['SHARES'].astype(int, errors='ignore')
    df['AMOUNT'] = [int(x[:-1])*1000 for x in df['AMOUNT']]
    df['NET P&L'] = ((df['NET P&L'].replace({'\$':''}, regex = True)).replace({',':''}, regex = True)).astype(float)
    #df['NET P&L'] = ((df['NET P&L'].replace({'\$':'', ',':''}, regex = True)).astype(float)
    df['CUMSUM']=df['NET P&L'].cumsum()
    df['PCT RETURN']=(df['CUMSUM']/300000)*100
    return df


'''
////////////////////// Below is to write to file /////////////////////////////////////////
Note that below I have deliberately left the range without a second value, it is just A1. 
This is because it should be able to work all relative to a single point, but we shall test it and see. 
'''
'''
aoa = [['Charlie', 'The GOAT'],['Sam', 'The Farmer']]

request = sheet.values().update(spreadsheetId=SAMPLE_SPREADSHEET_ID, 
                                range='TestSheet!A1', valueInputOption='USER_ENTERED', body={"values":aoa}).execute()

print(result)
'''  

def update_today_equity(equity_file, open_positions, realised_profit, interval):
    
    current_time = datetime.datetime.now().time()
    
    while datetime.time(14, 29, 0) < current_time < datetime.time(21, 1, 0):
        
        result = sheet.values().get(spreadsheetId=SAMPLE_SPREADSHEET_ID,
                            range='SPY TRADE TRACKER!!A1:H150').execute()
        values = result.get('values', [])
        
        tt_df = make_df(values)
        closed_trades = tt_df[~tt_df['EXIT DATE'].isna()]
        open_positions = tt_df[(tt_df['EXIT DATE'].isna()) & (~tt_df['SHARES'].isna())].copy()
        
        realised_profit = closed_trades['CUMSUM'].iloc[-1]
        
    
        shares = open_positions['SHARES'].sum()
        entry_value = (open_positions['OPEN PRICE'] * open_positions['SHARES']).sum()
        with open(r'C:\Users\Charlie\Documents\CVE\Python\API\TradeTracker - Live Graph\live_close.txt', 'r') as f:
            live_price = f.read()
            
        live_price = float(live_price)
        
        live_value = live_price * shares
        
        live_equity = round((live_value - entry_value + realised_profit), 2)
        
        write_string = f'\n{datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")},{live_equity}'
        
        with open(equity_file, 'a') as f:
            f.write(write_string)
        
        print(write_string)
        open_positions['PnL'] = ((open_positions['OPEN PRICE'] - live_price) * -1 * open_positions['SHARES']).round(2)
        open_positions.to_csv(r'C:\Users\Charlie\Documents\CVE\Python\API\TradeTracker - Live Graph\SPY_open_positions.csv', index=True)
        time.sleep(interval)
        current_time = datetime.datetime.now().time()
    
    if current_time > datetime.time(21,0,0):
        with open(equity_file, 'r') as f:
            prev_equity = f.read()
        with open(r'C:\Users\Charlie\Documents\CVE\Python\API\TradeTracker - Live Graph\historic_equity.csv', 'a') as f:
            f.write(prev_equity[12:])
            
        pd.DataFrame(columns=['Date', 'Equity']).to_csv(equity_file, index=False)
        
    

tt_df = make_df(values)
closed_trades = tt_df[~tt_df['EXIT DATE'].isna()]
open_positions = tt_df[tt_df['EXIT DATE'].isna()]

realised_profit = closed_trades['CUMSUM'].iloc[-1]

update_today_equity(r'C:\Users\Charlie\Documents\CVE\Python\API\TradeTracker - Live Graph\today_equity.csv',
                    open_positions,
                    realised_profit,
                    20)


