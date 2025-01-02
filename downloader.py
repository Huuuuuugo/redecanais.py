import threading
import warnings
import time
import os

import requests

class Download():
    def __init__(
            self, 
            url: str, 
            output_file: str,
            headers: dict | None = None, 
            max_retries: int = 0, 
            base_retry_delay: float = 0.5, 
            try_continue=True,
            except_status_codes: list[int] = None
            ):
        if not isinstance(url, str):
            message = f"Invalid type for 'url' attribute."
            raise TypeError(message)
        
        self.url = url
        self.output_file = output_file
        self.is_running = False
        self._interrupt_download = False
        self.base_retry_delay = base_retry_delay
        self.max_retries = max_retries

        self.try_continue = try_continue
        if except_status_codes is None:
            self.except_status_codes = [404, 403, 400, 405, 408, 410, 411, 412, 415, 429, 500, 501, 502, 503, 504]
        else:
            self.except_status_codes = except_status_codes

        if headers is None:
            self.headers = {}
        else:
            self.headers = headers.copy()

        if self.try_continue:
            # get ammount of bytes already written before beggining
            if os.path.exists(output_file):
                self.written_bytes = os.path.getsize(self.output_file)
            else:
                self.written_bytes = 0
            
            # set range to resume download if any byte has already been written
            if self.written_bytes:
                self.headers.update({"Range": f"bytes={self.written_bytes}-"})
        
        else:
            self.total_size = 0
            self.written_bytes = 0


    @property
    def progress(self):
        """Calculate the download progress as a percentage.

        Returns:
        --------
        float
            The progress of the download as a percentage (0 to 100).
        """

        if self.total_size:
            return (self.written_bytes / self.total_size) * 100

        else:
            return 0
        
        
    def _request_file(self):
        # make request and retry the defined ammount of times
        failed_request = False
        for attempt in range(self.max_retries + 1):
            try:
                self.response = requests.get(self.url, headers=self.headers, stream=True)

                # if the request returned a status code that suggests it's worthless to retry, raise exception
                if self.response.status_code in self.except_status_codes:
                    failed_request = True
                    message = f"Unexpected status code when requesting file size: {self.response.status_code}."
                    raise requests.RequestException(message)

                # if the request failed, but returned a status code that allow retrying, wait some time and then retry
                elif self.response.status_code not in range(200, 300):
                    message = f"Unexpected status code when requesting file: {self.response.status_code}. Retrying..."
                    warnings.warn(message, RuntimeWarning)

                    # exponentially increase wait time before retrying
                    wait_time = self.base_retry_delay * (2 ** attempt)
                    time.sleep(wait_time)

                # if the request was succesful, stop retrying
                else:
                    break
            
            # implements the retry logic even with exceptions raised by the requests module
            # this allows the program to continue if the connection times out, for example
            except requests.RequestException as e:
                # if the exception raised was generated by the retry logic, reraise it
                if failed_request:
                    raise e
                
                message = f"Exception raised when requesting file: {e}. Retrying..."
                warnings.warn(message, RuntimeWarning)

                # exponentially increase wait time before retrying
                wait_time = self.base_retry_delay * (2 ** attempt)
                time.sleep(wait_time)

        if self.try_continue:
            # store total_size inside a property
            try:
                self.total_size = int(self.response.headers['Content-Length']) + self.written_bytes

            except KeyError:
                message = f"The response has no 'Content-Length' header, resuming and progress tracking will not work. If the output file contains some data already, it will be completely cleared when 'start()' is called."
                warnings.warn(message, UserWarning)
                self.total_size = 0


    def _download(self):
            self.is_running = True
            # clear file if it doesn't support resuming
            if self.try_continue:
                if not self.total_size:
                    with open(self.output_file, 'wb') as file:
                        file.write(b'')
            
            else:
                with open(self.output_file, 'wb') as file:
                        file.write(b'')
            
            with open(self.output_file, 'ab') as file:
                for chunk in self.response.iter_content(chunk_size=8192):
                    if chunk:
                        self.written_bytes += len(chunk)
                        file.write(chunk)

                    if self._interrupt_download:
                        self.written_bytes = os.path.getsize(self.output_file)
                        break
                
                if not self._interrupt_download:
                    self.total_size = self.written_bytes
                    
            self.is_running = False
            self._interrupt_download = False

    
    def start(self, wait: bool = False):
        """Starts the download process in a separate thread.
        
        Warns:
        ------
        RuntimeWarning:
            If the download is already completed or currently running.
        
        Side Effects:
        -------------
        Spawns a new thread to handle the download process.
        """

        # request file
        self._request_file()
        
        # check for common mistakes
        if self.progress >= 100:
            message = "Can't start a download that's already finished."
            warnings.warn(message, RuntimeWarning)
            return
        
        if self.is_running:
            message = "Can't start a download that's already running."
            warnings.warn(message, RuntimeWarning)
            return
        
        # start downloading
        download_thread = threading.Thread(target=self._download, daemon=True)
        download_thread.start()
        if wait:
            download_thread.join()
    

    def stop(self):
        """Stops the current download if it is running.

        Warns:
        ------
        RuntimeWarning:
            If the download is not currently running.
        
        Side Effects:
        -------------
        Interrupts the download thread and waits for it to stop.
        """

        if not self.is_running:
            message = "Can't stop a download that's not running."
            warnings.warn(message, RuntimeWarning)
            return
        
        # set flag to interrupt the download thread and wait for it to properly stop
        self._interrupt_download = True
        while self.is_running:
            time.sleep(0.001)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        exit("Example usage: python downloader.py <url> <output-file>")

    url = sys.argv[1]
    output_file = sys.argv[2]

    Download(url, output_file, max_retries=6).start()

    Download.wait_downloads()