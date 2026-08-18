# Chaincode-as-a-Service (CCaaS) image for the AI-EDGE governance contract.
# The peer connects to this long-running service over gRPC — it does NOT build a
# chaincode image itself, so this is runtime-agnostic (works with Docker's
# containerd image store, BuildKit, podman, and Kubernetes).
FROM node:18-alpine

WORKDIR /usr/src/app

# Install deps first for layer caching.
COPY package.json ./
RUN npm install --omit=dev

# Chaincode source.
COPY index.js ./
COPY lib ./lib

# CHAINCODE_SERVER_ADDRESS and CHAINCODE_ID are injected at run time.
EXPOSE 9999
CMD ["npm", "run", "start:server"]
