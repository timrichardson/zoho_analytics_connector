""" Wrapper class over Zoho's ReportClient. This is more modern and higher level.

"""


import csv
from typing import MutableMapping,MutableSequence,Optional
import logging
logger = logging.getLogger(__name__)
import time
import json

import requests
from . import report_client

""" add some helper functions on top of report_client"""

class EnhancedZohoReportClient(report_client.ReportClient):

    @staticmethod
    def process_table_meta_data(catalog):
        """ catalog is a ZOHO_CATALOG_INFO dict. Call this from get_database_metadata for example
         Return a dict keyed by tablename, each item being a dict keyed by column name, with the item being the catalog info for the col
         So all the table names can be found as table_data.keys()
         for for a given table name, the column names are table_data['table1'].keys()
         and to find the column meta data such as dataType:
         data['table1']['col1']['typeName']
         Zoho gives each type an integer coding ['dataType'], a descriptive datatype name ['typeName'], and some other meta data.

         """
        db_name = catalog['tableCat']
        table_data = {}
        for table in catalog['views']:
            if table['tableType'] == 'TABLE':
                table_data[table['tableName']] = {}
                col_data = table_data[table['tableName']]
                for col in table['columns']:
                    col_data[col['columnName']] = col

        return table_data


    def __init__(self, login_email_id:str, authtoken:str, default_databasename:str=None):
        self.login_email_id = login_email_id
        self.authtoken = authtoken
        self.default_databasename = default_databasename
        super().__init__(authtoken=authtoken)


    def get_database_catalog(self, database_name: str = None) -> MutableMapping:
        db_uri = self.getDBURI(self.login_email_id, database_name or self.default_databasename)
        catalog_info = self.getDatabaseMetadata(requestURI=db_uri, metadata="ZOHO_CATALOG_INFO")
        return catalog_info


    def get_table_metadata(self ,database_name:str=None ) ->MutableMapping:
        database_name = database_name or self.default_databasename
        catalog_info = self.get_database_catalog(database_name=database_name)
        table_metadata = self.process_table_meta_data(catalog_info)
        return table_metadata


    def create_table(self, table_design,database_name=None) -> MutableMapping:
        db_uri = self.getDBURI(self.login_email_id, database_name or self.default_databasename)
        columns = table_design['COLUMNS']
        if len(columns) < 70: # too many columns and zoho rejects the very long URL
            result = self.createTable(dbURI=db_uri,tableDesign=json.dumps(table_design))
        else:
            columns_initial,columns_residual =columns[:70],columns[70:]
            table_design['COLUMNS'] = columns_initial
            table_name=table_design['TABLENAME']
            result = self.createTable(dbURI=db_uri, tableDesign=json.dumps(table_design))
            uri_addcol = self.getURI(self.login_email_id, database_name or self.default_databasename, tableOrReportName=table_name)
            for col in columns_residual:
                self.addColumn(tableURI=uri_addcol,columnName=col['COLUMNNAME'],dataType=col['DATATYPE'])

        return result


    def data_upload(self,import_content:str,table_name:str,import_mode="TRUNCATEADD",
                    matching_columns=Optional[str],
                    database_name:str=Optional[str],
                    retry_limit=0)->Optional[report_client.ImportResult]:
        """ data is a csv-style string, newline separated. Matching columns is a comma separated string"""
        retry_count = 0
        impResult = None
        uri = self.getURI(dbOwnerName=self.login_email_id, dbName=database_name or self.default_databasename, tableOrReportName=table_name)

            # import_modes = APPEND / TRUNCATEADD / UPDATEADD
        while True:

            retry_count += 1
            try:
                impResult = self.import_data(uri, import_mode=import_mode, import_content=import_content,matching_columns=matching_columns)
                if impResult.result_code == 6001: #API limit exceeded
                    logger.error("API limit exceeded")
                    raise RuntimeError("API limit exceeded")
                else:
                    logger.debug(
                        f"Table: {table_name}: Processed Rows: {impResult.totalRowCount} with {impResult.warningCount} warnings ")
                break
            except report_client.ParseError:
                if retry_count <= retry_limit:
                    logger.info(f"Retrying data_upload because of upload error")
                    time.sleep(1)
                    continue
                else:
                    logger.info(f"Number of retry attempts exceeded")
                    raise(requests.exceptions.ConnectionError)
        return impResult


    def data_export_using_sql(self,sql,table_name, database_name: str = None)->csv.DictReader:
        """ returns a csv.DictReader after querying with the sql provided.
        The Zoho API insists on a table or report name, but it doesn't seem to restrict the query"""

        uri = self.getURI(dbOwnerName=self.login_email_id, dbName=database_name or self.default_databasename,
                          tableOrReportName=table_name)
        r = self.exportDataUsingSQL(tableOrReportURI=uri, format='CSV', sql=sql)
        if r.status_code == 200:
            reader = csv.DictReader(r.content.decode('utf-8').splitlines())
        else:
            error_response = report_client.ServerError(r)
            logger.info(f"Error in zoho sql export: {error_response.message}")
            reader = None
        return reader


    def delete_rows(self,table_name,sql, database_name: Optional[str] = None):
        uri = self.getURI(dbOwnerName=self.login_email_id, dbName=database_name or self.default_databasename,
                          tableOrReportName=table_name)

        r = self.deleteData(tableURI=uri,criteria=sql)
        return r
