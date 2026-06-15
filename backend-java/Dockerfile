ARG DOCKERHUB_LIBRARY_PREFIX=
FROM ${DOCKERHUB_LIBRARY_PREFIX}maven:3.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

ARG DOCKERHUB_LIBRARY_PREFIX=
FROM ${DOCKERHUB_LIBRARY_PREFIX}eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /workspace/target/backend-java-0.1.0.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
